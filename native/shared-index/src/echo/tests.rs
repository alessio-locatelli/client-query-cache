use std::sync::Arc;

use super::*;
use crate::index::{Layout, Writer};
use crate::memory::zeroed;
use crate::sync::AtomicU64;

const EPOCH: u64 = 3;

fn published() -> Index<Arc<[AtomicU64]>> {
    let layout = Layout::new(8, 64, 1, 1).unwrap();
    let index = Index::create(zeroed(layout.words()), layout, 5, u64::MAX).unwrap();
    assert!(index.set_available(0, true) && index.set_progress(0, 1) && index.set_epoch(0, EPOCH));
    let query = Query {
        database: 0,
        namespace: 0,
        epoch: EPOCH,
        identity: b"present",
        shape: b"shape",
    };
    let mut writer = Writer::new(index.clone());
    let payload = writer.store(b"payload").unwrap();
    writer.publish(&query, payload).unwrap();
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

fn connection() -> (Connection, UnixStream) {
    let (stream, peer) = UnixStream::pair().unwrap();
    stream.set_nonblocking(true).unwrap();
    let connection = Connection {
        stream,
        inbox: Vec::new(),
        outbox: Vec::new(),
        sent: 0,
        writable: false,
    };
    (connection, peer)
}

#[test]
fn rejects_more_selections_than_one_frame_may_carry() {
    let index = published();
    let identities = vec![&b"present"[..]; SELECTION_LIMIT as usize + 1];
    let frame = request(9, &identities);
    assert!(answer_frame(&index, 5, &frame[LENGTH_BYTES..], 1, &mut Vec::new()).is_err());
    let frame = request(9, &identities[1..]);
    assert!(answer_frame(&index, 5, &frame[LENGTH_BYTES..], 1, &mut Vec::new()).is_ok());
}

#[test]
fn rejects_replies_larger_than_a_frame() {
    let payload = vec![7_u8; REPLY_LIMIT / 9];
    let layout = Layout::new(8, payload.len(), 1, 1).unwrap();
    let index = Index::create(zeroed(layout.words()), layout, 5, u64::MAX).unwrap();
    assert!(index.set_available(0, true) && index.set_progress(0, 1) && index.set_epoch(0, EPOCH));
    let mut writer = Writer::new(index.clone());
    let stored = writer.store(&payload).unwrap();
    let query = Query {
        database: 0,
        namespace: 0,
        epoch: EPOCH,
        identity: b"present",
        shape: b"shape",
    };
    writer.publish(&query, stored).unwrap();
    let fits = request(9, &[&b"present"[..]; 8]);
    assert!(answer_frame(&index, 5, &fits[LENGTH_BYTES..], 1, &mut Vec::new()).is_ok());
    let oversized = request(9, &[&b"present"[..]; 9]);
    assert!(answer_frame(&index, 5, &oversized[LENGTH_BYTES..], 1, &mut Vec::new()).is_err());
}

#[test]
fn closes_a_connection_whose_replies_are_not_read() {
    let index = published();
    let (mut connection, _peer) = connection();
    connection.outbox = vec![0; QUEUE_LIMIT];
    connection.inbox = request(9, &[b"present"]);
    assert!(connection.answer(&index, 5).is_err());
    connection
        .outbox
        .truncate(QUEUE_LIMIT - expected_reply(9).len());
    connection.inbox = request(9, &[b"present", b"absent"]);
    assert!(connection.answer(&index, 5).is_ok());
}

#[test]
fn buffers_at_most_one_frame_of_unanswered_input() {
    let (mut connection, mut peer) = connection();
    let writer = std::thread::spawn(move || {
        let _ = peer.write_all(&vec![0xff; 2 * INBOX_LIMIT]);
    });
    let mut scratch = vec![0_u8; RECEIVE_BYTES];
    while connection.inbox.len() < INBOX_LIMIT {
        assert!(connection.receive(&mut scratch));
    }
    assert!(connection.receive(&mut scratch));
    assert_eq!(connection.inbox.len(), INBOX_LIMIT);
    drop(connection);
    writer.join().unwrap();
}

struct EchoSocket {
    echo: Echo,
    directory: std::path::PathBuf,
}

impl Drop for EchoSocket {
    fn drop(&mut self) {
        self.echo.stop();
        std::fs::remove_dir_all(&self.directory).unwrap();
    }
}

fn echo_socket() -> (EchoSocket, UnixStream) {
    let directory = std::env::temp_dir().join("agents").join(format!(
        "shared-index-echo-{}-{}",
        std::process::id(),
        monotonic_ns()
    ));
    std::fs::create_dir_all(&directory).unwrap();
    let path = directory.join("echo.sock");
    let echo = Echo::start(published(), UnixListener::bind(&path).unwrap()).unwrap();
    let client = UnixStream::connect(&path).unwrap();
    (EchoSocket { echo, directory }, client)
}

#[test]
fn serves_frames_split_across_reads_over_a_socket() {
    let (_server, mut client) = echo_socket();
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
}

#[test]
fn backpressure_preserves_unsent_reply_bytes() {
    let (mut connection, mut peer) = connection();
    let poller = Poller::new().unwrap();
    poller
        .control(
            libc::EPOLL_CTL_ADD,
            connection.stream.as_raw_fd(),
            FIRST_CONNECTION,
            libc::EPOLLIN,
        )
        .unwrap();
    let expected = vec![b'r'; 2 * FRAME_LIMIT];
    connection.outbox.clone_from(&expected);
    let mut received = Vec::new();
    assert!(connection.flush(&poller, FIRST_CONNECTION));
    assert!(connection.writable);
    assert!(connection.sent > 0 && connection.sent < expected.len());
    while !connection.outbox.is_empty() {
        let sent = connection.sent;
        let start = received.len();
        received.resize(sent, 0);
        peer.read_exact(&mut received[start..]).unwrap();
        assert!(connection.flush(&poller, FIRST_CONNECTION));
    }
    let start = received.len();
    received.resize(expected.len(), 0);
    peer.read_exact(&mut received[start..]).unwrap();
    assert_eq!(received, expected);
    assert!(!connection.writable);
    assert_eq!(connection.sent, 0);
}

#[test]
fn closed_peer_rejects_pending_replies() {
    let (mut connection, peer) = connection();
    drop(peer);
    connection.outbox.extend_from_slice(b"reply");
    assert!(!connection.flush(&Poller::new().unwrap(), FIRST_CONNECTION));
}

#[test]
fn peer_reset_closes_the_connection() {
    let (mut connection, peer) = connection();
    connection.stream.write_all(b"unread reply").unwrap();
    drop(peer);
    assert!(!connection.receive(&mut [0; 64]));
}

struct IgnoredUserSignal(libc::sigaction);

extern "C" fn ignore_user_signal(_signal: libc::c_int) {}

impl IgnoredUserSignal {
    fn install() -> Self {
        let mut action = unsafe { std::mem::zeroed::<libc::sigaction>() };
        action.sa_sigaction = ignore_user_signal as *const () as usize;
        assert_eq!(unsafe { libc::sigemptyset(&raw mut action.sa_mask) }, 0);
        let mut previous = unsafe { std::mem::zeroed::<libc::sigaction>() };
        assert_eq!(
            unsafe { libc::sigaction(libc::SIGUSR1, &raw const action, &raw mut previous) },
            0
        );
        Self(previous)
    }
}

impl Drop for IgnoredUserSignal {
    fn drop(&mut self) {
        assert_eq!(
            unsafe { libc::sigaction(libc::SIGUSR1, &raw const self.0, std::ptr::null_mut()) },
            0
        );
    }
}

#[test]
fn signals_do_not_stop_the_echo_server() {
    use std::os::unix::thread::JoinHandleExt;
    use std::time::Duration;

    let _handler = IgnoredUserSignal::install();
    let (server, mut client) = echo_socket();
    client
        .set_read_timeout(Some(Duration::from_secs(3)))
        .unwrap();
    let thread = server.echo.thread.as_ref().unwrap().as_pthread_t();
    for request_id in 0..8 {
        std::thread::sleep(Duration::from_millis(1));
        assert_eq!(unsafe { libc::pthread_kill(thread, libc::SIGUSR1) }, 0);
        let frame = request(request_id, &[]);
        client.write_all(&frame).unwrap();
        let mut reply = vec![0; frame.len()];
        client.read_exact(&mut reply).unwrap();
        assert_eq!(reply, frame);
    }
}
