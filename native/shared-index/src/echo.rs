use std::collections::HashMap;
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::net::{UnixListener, UnixStream};
use std::thread::JoinHandle;

use crate::clock::monotonic_ns;
use crate::index::{Index, Query};
use crate::memory::Words;

pub(crate) const FRAME_LIMIT: usize = 1_048_576 + 65_536;
pub(crate) const MISS: u32 = u32::MAX;
const LENGTH_BYTES: usize = 4;
const SELECTION_BYTES: usize = 24;
const LISTENER: u64 = 0;
const STOP: u64 = 1;
const FIRST_CONNECTION: u64 = 2;
const EVENTS: usize = 64;
const RECEIVE_BYTES: usize = 65_536;
const SELECTION_LIMIT: u32 = 16;
const REPLY_LIMIT: usize = FRAME_LIMIT;
const INBOX_LIMIT: usize = LENGTH_BYTES + FRAME_LIMIT;
const QUEUE_LIMIT: usize = 4 * FRAME_LIMIT;

#[derive(Debug)]
pub(crate) struct FrameError;

fn checked(result: libc::c_int) -> io::Result<libc::c_int> {
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(result)
    }
}

struct Poller(OwnedFd);

impl Poller {
    fn new() -> io::Result<Self> {
        let fd = checked(unsafe { libc::epoll_create1(libc::EPOLL_CLOEXEC) })?;
        Ok(Self(unsafe { OwnedFd::from_raw_fd(fd) }))
    }

    fn control(
        &self,
        operation: libc::c_int,
        fd: RawFd,
        token: u64,
        events: libc::c_int,
    ) -> io::Result<()> {
        let mut event = libc::epoll_event {
            events: events as u32,
            u64: token,
        };
        checked(unsafe { libc::epoll_ctl(self.0.as_raw_fd(), operation, fd, &mut event) }).map(drop)
    }

    fn wait(&self, events: &mut [libc::epoll_event]) -> io::Result<usize> {
        let ready = checked(unsafe {
            libc::epoll_wait(
                self.0.as_raw_fd(),
                events.as_mut_ptr(),
                events.len() as libc::c_int,
                -1,
            )
        })?;
        Ok(ready as usize)
    }
}

fn u32_at(bytes: &[u8], at: usize) -> Result<u32, FrameError> {
    let field = bytes.get(at..at + 4).ok_or(FrameError)?;
    Ok(u32::from_le_bytes(
        field.try_into().map_err(|_| FrameError)?,
    ))
}

fn u64_at(bytes: &[u8], at: usize) -> Result<u64, FrameError> {
    let field = bytes.get(at..at + 8).ok_or(FrameError)?;
    Ok(u64::from_le_bytes(
        field.try_into().map_err(|_| FrameError)?,
    ))
}

pub(crate) fn answer_frame<M: Words>(
    index: &Index<M>,
    incarnation: u64,
    body: &[u8],
    now_ns: u64,
    out: &mut Vec<u8>,
) -> Result<(), FrameError> {
    let request_id = u32_at(body, 0)?;
    let count = u32_at(body, 4)?;
    if count > SELECTION_LIMIT {
        return Err(FrameError);
    }
    let mut rest = body.get(8..).ok_or(FrameError)?;
    let start = out.len();
    out.extend_from_slice(&[0; LENGTH_BYTES]);
    out.extend_from_slice(&request_id.to_le_bytes());
    out.extend_from_slice(&count.to_le_bytes());
    for _ in 0..count {
        let identity_len = u32_at(rest, 16)? as usize;
        let shape_len = u32_at(rest, 20)? as usize;
        let identity_end = SELECTION_BYTES
            .checked_add(identity_len)
            .ok_or(FrameError)?;
        let shape_end = identity_end.checked_add(shape_len).ok_or(FrameError)?;
        let query = Query {
            database: u32_at(rest, 0)? as usize,
            namespace: u32_at(rest, 4)? as usize,
            epoch: u64_at(rest, 8)?,
            identity: rest.get(SELECTION_BYTES..identity_end).ok_or(FrameError)?,
            shape: rest.get(identity_end..shape_end).ok_or(FrameError)?,
        };
        rest = &rest[shape_end..];
        let mark = out.len();
        out.extend_from_slice(&MISS.to_le_bytes());
        let mut oversized = false;
        let served = index.read(incarnation, &query, now_ns, |located| {
            out.truncate(mark + LENGTH_BYTES);
            let end = mark + LENGTH_BYTES + located.payload_len;
            if end - start - LENGTH_BYTES > REPLY_LIMIT {
                oversized = true;
                return None;
            }
            out.resize(end, 0);
            index
                .copy_payload(located, &mut out[mark + LENGTH_BYTES..])
                .then_some(located.payload_len)
        });
        if oversized {
            return Err(FrameError);
        }
        match served {
            Ok((length, _token)) => {
                out[mark..mark + LENGTH_BYTES].copy_from_slice(&(length as u32).to_le_bytes());
            }
            Err(_) => out.truncate(mark + LENGTH_BYTES),
        }
    }
    if !rest.is_empty() {
        return Err(FrameError);
    }
    let length = (out.len() - start - LENGTH_BYTES) as u32;
    out[start..start + LENGTH_BYTES].copy_from_slice(&length.to_le_bytes());
    Ok(())
}

struct Connection {
    stream: UnixStream,
    inbox: Vec<u8>,
    outbox: Vec<u8>,
    sent: usize,
    writable: bool,
}

impl Connection {
    fn receive(&mut self, scratch: &mut [u8]) -> bool {
        loop {
            let room = INBOX_LIMIT
                .saturating_sub(self.inbox.len())
                .min(scratch.len());
            if room == 0 {
                return true;
            }
            match self.stream.read(&mut scratch[..room]) {
                Ok(0) => return false,
                Ok(received) => self.inbox.extend_from_slice(&scratch[..received]),
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => return true,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(_) => return false,
            }
        }
    }

    fn answer<M: Words>(&mut self, index: &Index<M>, incarnation: u64) -> Result<(), FrameError> {
        let now_ns = monotonic_ns();
        let mut consumed = 0;
        while let Ok(length) = u32_at(&self.inbox, consumed) {
            let length = length as usize;
            if length > FRAME_LIMIT {
                return Err(FrameError);
            }
            let end = consumed + LENGTH_BYTES + length;
            let Some(body) = self.inbox.get(consumed + LENGTH_BYTES..end) else {
                break;
            };
            answer_frame(index, incarnation, body, now_ns, &mut self.outbox)?;
            consumed = end;
            if self.outbox.len() - self.sent > QUEUE_LIMIT {
                return Err(FrameError);
            }
        }
        self.inbox.drain(..consumed);
        Ok(())
    }

    fn flush(&mut self, poller: &Poller, token: u64) -> bool {
        while self.sent < self.outbox.len() {
            match self.stream.write(&self.outbox[self.sent..]) {
                Ok(0) => return false,
                Ok(written) => self.sent += written,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(_) => return false,
            }
        }
        if self.sent == self.outbox.len() {
            self.outbox.clear();
            self.sent = 0;
        }
        let writable = !self.outbox.is_empty();
        if writable == self.writable {
            return true;
        }
        self.writable = writable;
        let events = libc::EPOLLIN | if writable { libc::EPOLLOUT } else { 0 };
        poller
            .control(libc::EPOLL_CTL_MOD, self.stream.as_raw_fd(), token, events)
            .is_ok()
    }
}

fn accept_all(
    listener: &UnixListener,
    poller: &Poller,
    connections: &mut HashMap<u64, Connection>,
    next: &mut u64,
) {
    loop {
        let Ok((stream, _address)) = listener.accept() else {
            return;
        };
        if stream.set_nonblocking(true).is_err()
            || poller
                .control(
                    libc::EPOLL_CTL_ADD,
                    stream.as_raw_fd(),
                    *next,
                    libc::EPOLLIN,
                )
                .is_err()
        {
            continue;
        }
        connections.insert(
            *next,
            Connection {
                stream,
                inbox: Vec::new(),
                outbox: Vec::new(),
                sent: 0,
                writable: false,
            },
        );
        *next += 1;
    }
}

fn serve<M: Words>(index: Index<M>, listener: UnixListener, poller: Poller) {
    let incarnation = index.incarnation();
    let mut connections = HashMap::new();
    let mut next = FIRST_CONNECTION;
    let mut events = [libc::epoll_event { events: 0, u64: 0 }; EVENTS];
    let mut scratch = vec![0_u8; RECEIVE_BYTES];
    loop {
        let ready = match poller.wait(&mut events) {
            Ok(ready) => ready,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return,
        };
        for event in &events[..ready] {
            let token = event.u64;
            match token {
                STOP => return,
                LISTENER => accept_all(&listener, &poller, &mut connections, &mut next),
                _ => {
                    let Some(connection) = connections.get_mut(&token) else {
                        continue;
                    };
                    let keep = connection.receive(&mut scratch)
                        && connection.answer(&index, incarnation).is_ok()
                        && connection.flush(&poller, token);
                    if !keep {
                        connections.remove(&token);
                    }
                }
            }
        }
    }
}

pub(crate) struct Echo {
    stop: OwnedFd,
    thread: Option<JoinHandle<()>>,
}

impl Echo {
    pub(crate) fn start<M: Words + Send + 'static>(
        index: Index<M>,
        listener: UnixListener,
    ) -> io::Result<Self> {
        listener.set_nonblocking(true)?;
        let stop = checked(unsafe { libc::eventfd(0, libc::EFD_CLOEXEC | libc::EFD_NONBLOCK) })?;
        let stop = unsafe { OwnedFd::from_raw_fd(stop) };
        let poller = Poller::new()?;
        poller.control(
            libc::EPOLL_CTL_ADD,
            listener.as_raw_fd(),
            LISTENER,
            libc::EPOLLIN,
        )?;
        poller.control(libc::EPOLL_CTL_ADD, stop.as_raw_fd(), STOP, libc::EPOLLIN)?;
        let thread = std::thread::Builder::new()
            .name("shared-index-echo".into())
            .spawn(move || serve(index, listener, poller))?;
        Ok(Self {
            stop,
            thread: Some(thread),
        })
    }

    pub(crate) fn stop(&mut self) {
        let Some(thread) = self.thread.take() else {
            return;
        };
        let signal = 1_u64.to_ne_bytes();
        unsafe {
            libc::write(self.stop.as_raw_fd(), signal.as_ptr().cast(), signal.len());
        }
        let _ = thread.join();
    }
}

impl Drop for Echo {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests;
