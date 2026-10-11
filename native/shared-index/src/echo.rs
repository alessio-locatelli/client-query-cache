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
        let served = index.read(incarnation, &query, now_ns, |located| {
            out.truncate(mark + LENGTH_BYTES);
            out.resize(mark + LENGTH_BYTES + located.payload_len, 0);
            index
                .copy_payload(located, &mut out[mark + LENGTH_BYTES..])
                .then_some(located.payload_len)
        });
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
            match self.stream.read(scratch) {
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
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::index::{Layout, Writer};
    use crate::memory::zeroed;
    use crate::sync::AtomicU64;

    const EPOCH: u64 = 3;

    fn published() -> Index<Arc<[AtomicU64]>> {
        let layout = Layout::new(8, 64, 1, 1).unwrap();
        let index = Index::create(zeroed(layout.words()), layout, 5, u64::MAX).unwrap();
        assert!(
            index.set_available(0, true) && index.set_progress(0, 1) && index.set_epoch(0, EPOCH)
        );
        let query = Query {
            database: 0,
            namespace: 0,
            epoch: EPOCH,
            identity: b"present",
            shape: b"shape",
        };
        Writer::new(index.clone())
            .publish(&query, b"payload", 1)
            .unwrap();
        index
    }

    fn selection(identity: &[u8]) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&0_u32.to_le_bytes());
        bytes.extend_from_slice(&EPOCH.to_le_bytes());
        bytes.extend_from_slice(&(identity.len() as u32).to_le_bytes());
        bytes.extend_from_slice(&5_u32.to_le_bytes());
        bytes.extend_from_slice(identity);
        bytes.extend_from_slice(b"shape");
        bytes
    }

    fn request(request_id: u32, identities: &[&[u8]]) -> Vec<u8> {
        let mut body = Vec::new();
        body.extend_from_slice(&request_id.to_le_bytes());
        body.extend_from_slice(&(identities.len() as u32).to_le_bytes());
        for identity in identities {
            body.extend_from_slice(&selection(identity));
        }
        let mut frame = (body.len() as u32).to_le_bytes().to_vec();
        frame.extend_from_slice(&body);
        frame
    }

    fn expected_reply(request_id: u32) -> Vec<u8> {
        let mut body = Vec::new();
        body.extend_from_slice(&request_id.to_le_bytes());
        body.extend_from_slice(&2_u32.to_le_bytes());
        body.extend_from_slice(&7_u32.to_le_bytes());
        body.extend_from_slice(b"payload");
        body.extend_from_slice(&MISS.to_le_bytes());
        let mut frame = (body.len() as u32).to_le_bytes().to_vec();
        frame.extend_from_slice(&body);
        frame
    }

    #[test]
    fn answers_each_selection_in_order() {
        let index = published();
        let mut out = Vec::new();
        let frame = request(9, &[b"present", b"absent"]);
        answer_frame(&index, 5, &frame[LENGTH_BYTES..], 1, &mut out).unwrap();
        assert_eq!(out, expected_reply(9));
    }

    #[test]
    fn rejects_malformed_frames() {
        let index = published();
        let frame = request(9, &[b"present"]);
        let body = &frame[LENGTH_BYTES..];
        let mut overstated = body.to_vec();
        overstated[4] = 2;
        let mut trailing = body.to_vec();
        trailing.push(0);
        for malformed in [
            &body[..body.len() - 1],
            &body[..6],
            &overstated[..],
            &trailing[..],
        ] {
            assert!(answer_frame(&index, 5, malformed, 1, &mut Vec::new()).is_err());
        }
    }

    #[test]
    fn serves_frames_split_across_reads_over_a_socket() {
        let directory =
            std::env::temp_dir().join(format!("shared-index-echo-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join("echo.sock");
        let _ = std::fs::remove_file(&path);
        let mut echo = Echo::start(published(), UnixListener::bind(&path).unwrap()).unwrap();
        let mut client = UnixStream::connect(&path).unwrap();
        let mut frames = request(1, &[b"present", b"absent"]);
        frames.extend_from_slice(&request(2, &[b"present", b"absent"]));
        let (first, second) = frames.split_at(10);
        client.write_all(first).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(20));
        client.write_all(second).unwrap();
        let mut expected = expected_reply(1);
        expected.extend_from_slice(&expected_reply(2));
        let mut reply = vec![0; expected.len()];
        client.read_exact(&mut reply).unwrap();
        assert_eq!(reply, expected);
        echo.stop();
        std::fs::remove_dir_all(&directory).unwrap();
    }
}
