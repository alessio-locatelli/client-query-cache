pub(crate) fn monotonic_ns() -> u64 {
    let mut now = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    unsafe {
        libc::clock_gettime(libc::CLOCK_MONOTONIC, &raw mut now);
    }
    (now.tv_sec as u64) * 1_000_000_000 + now.tv_nsec as u64
}
