use std::io::{self, Read, Write};
use std::net::{Shutdown, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, PoisonError};
use std::thread;

const BUFFER_BYTES: usize = 65_536;

struct Forwarding {
    open: bool,
    stopped: bool,
}

struct Control {
    forwarding: Mutex<Forwarding>,
    resumed: Condvar,
    sent: AtomicU64,
    received: AtomicU64,
}

#[derive(Clone)]
pub(crate) struct Relay(Arc<Control>);

impl Relay {
    pub(crate) fn new() -> Self {
        Self(Arc::new(Control {
            forwarding: Mutex::new(Forwarding {
                open: true,
                stopped: false,
            }),
            resumed: Condvar::new(),
            sent: AtomicU64::new(0),
            received: AtomicU64::new(0),
        }))
    }

    pub(crate) fn pause(&self) {
        self.0
            .forwarding
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .open = false;
    }

    pub(crate) fn resume(&self) {
        self.0
            .forwarding
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .open = true;
        self.0.resumed.notify_all();
    }

    pub(crate) fn stop(&self) {
        self.0
            .forwarding
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .stopped = true;
        self.0.resumed.notify_all();
    }

    pub(crate) fn sent(&self) -> u64 {
        self.0.sent.load(Ordering::Relaxed)
    }

    pub(crate) fn received(&self) -> u64 {
        self.0.received.load(Ordering::Relaxed)
    }

    fn wait(&self) -> bool {
        let mut forwarding = self
            .0
            .forwarding
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        while !forwarding.open && !forwarding.stopped {
            forwarding = self
                .0
                .resumed
                .wait(forwarding)
                .unwrap_or_else(PoisonError::into_inner);
        }
        !forwarding.stopped
    }

    fn pump(&self, mut source: TcpStream, mut destination: TcpStream, count: &AtomicU64) {
        let mut buffer = [0; BUFFER_BYTES];
        'receiving: loop {
            let length = match source.read(&mut buffer) {
                Ok(0) => break,
                Ok(length) => length,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            };
            if !self.wait() {
                break;
            }
            let mut pending = &buffer[..length];
            while !pending.is_empty() {
                match destination.write(pending) {
                    Ok(0) => break 'receiving,
                    Ok(written) => {
                        count.fetch_add(written as u64, Ordering::Relaxed);
                        pending = &pending[written..];
                    }
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(_) => break 'receiving,
                }
            }
        }
        // Flush each direction before propagating its EOF; the peer may still reply.
        let _ = destination.shutdown(Shutdown::Write);
    }

    pub(crate) fn forward(&self, client: TcpStream, upstream: TcpStream) -> io::Result<()> {
        let returning_source = upstream.try_clone()?;
        let returning_destination = client.try_clone()?;
        thread::scope(|scope| {
            let returning = thread::Builder::new()
                .name("benchmark-relay-return".into())
                .spawn_scoped(scope, || {
                    self.pump(returning_source, returning_destination, &self.0.received);
                })?;
            self.pump(client, upstream, &self.0.sent);
            returning
                .join()
                .map_err(|_| io::Error::other("benchmark relay thread panicked"))
        })
    }
}

#[cfg(test)]
mod tests;
