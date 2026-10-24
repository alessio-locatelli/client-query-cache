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

fn reset_peer() -> TcpStream {
    use std::os::fd::AsRawFd;

    let (peer, connection) = pair();
    let linger = libc::linger {
        l_onoff: 1,
        l_linger: 0,
    };
    assert_eq!(
        unsafe {
            libc::setsockopt(
                peer.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_LINGER,
                (&raw const linger).cast(),
                std::mem::size_of_val(&linger) as libc::socklen_t,
            )
        },
        0
    );
    drop(peer);
    connection
}

#[test]
fn socket_resets_stop_forwarding_without_counting_rejected_bytes() {
    for reset_source in [true, false] {
        let relay = Relay::new();
        let (mut sender, source) = pair();
        let (_receiver, destination) = pair();
        sender.write_all(b"unsent").unwrap();
        sender.shutdown(Shutdown::Write).unwrap();
        if reset_source {
            relay.pump(reset_peer(), destination, &relay.0.sent);
        } else {
            relay.pump(source, reset_peer(), &relay.0.sent);
        }
        assert_eq!(relay.sent(), 0);
    }
}
