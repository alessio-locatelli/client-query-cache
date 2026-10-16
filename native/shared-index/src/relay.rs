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
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::time::Duration;

    fn pair() -> (TcpStream, TcpStream) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        (client, listener.accept().unwrap().0)
    }

    #[test]
    fn counts_full_duplex_bytes_and_preserves_half_close() {
        let relay = Relay::new();
        for length in [0, 1, BUFFER_BYTES, 4 * 1024 * 1024] {
            let payload: Vec<u8> = (0..length).map(|index| index as u8).collect();
            let reply: Vec<u8> = payload.iter().rev().copied().collect();
            let (mut client, incoming) = pair();
            let (outgoing, mut server) = pair();
            thread::scope(|scope| {
                let forwarding = scope.spawn(|| relay.forward(incoming, outgoing).unwrap());
                let application = scope.spawn(|| {
                    client.write_all(&payload).unwrap();
                    client.shutdown(Shutdown::Write).unwrap();
                    let mut received = Vec::new();
                    client.read_to_end(&mut received).unwrap();
                    assert_eq!(received, reply);
                });
                let mut received = Vec::new();
                server.read_to_end(&mut received).unwrap();
                assert_eq!(received, payload);
                server.write_all(&reply).unwrap();
                server.shutdown(Shutdown::Write).unwrap();
                application.join().unwrap();
                forwarding.join().unwrap();
            });
        }
        let expected = (1 + BUFFER_BYTES + 4 * 1024 * 1024) as u64;
        assert_eq!(relay.sent(), expected);
        assert_eq!(relay.received(), expected);
    }

    #[test]
    fn pause_blocks_forwarding_until_resume() {
        let relay = Relay::new();
        let (mut client, incoming) = pair();
        let (outgoing, mut server) = pair();
        server
            .set_read_timeout(Some(Duration::from_millis(30)))
            .unwrap();
        relay.pause();
        thread::scope(|scope| {
            let forwarding = scope.spawn(|| relay.forward(incoming, outgoing).unwrap());
            client.write_all(b"paused request").unwrap();
            let mut request = [0; 14];
            let error = server.read(&mut request).unwrap_err();
            assert!(matches!(
                error.kind(),
                io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut
            ));
            assert_eq!(relay.sent(), 0);
            relay.resume();
            server.set_read_timeout(None).unwrap();
            server.read_exact(&mut request).unwrap();
            assert_eq!(&request, b"paused request");
            client.shutdown(Shutdown::Write).unwrap();
            server.shutdown(Shutdown::Write).unwrap();
            forwarding.join().unwrap();
        });
        assert_eq!(relay.sent(), 14);
        assert_eq!(relay.received(), 0);
    }

    #[test]
    fn stop_releases_paused_forwarding_without_sending() {
        let relay = Relay::new();
        let (mut client, incoming) = pair();
        let (outgoing, mut server) = pair();
        relay.pause();
        thread::scope(|scope| {
            let forwarding = scope.spawn(|| relay.forward(incoming, outgoing).unwrap());
            client.write_all(b"discard on teardown").unwrap();
            relay.stop();
            server.shutdown(Shutdown::Write).unwrap();
            assert_eq!(server.read(&mut [0]).unwrap(), 0);
            forwarding.join().unwrap();
        });
        assert_eq!(relay.sent(), 0);
        assert_eq!(relay.received(), 0);
    }
}
