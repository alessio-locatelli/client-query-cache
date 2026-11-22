use std::fs::OpenOptions;
use std::io::Write;
use std::os::fd::{AsFd, AsRawFd};

use super::*;
use crate::sync::Ordering;

#[test]
fn sealed_memory_stays_writable_only_through_the_owner_mapping() {
    let (owner, descriptor) = Mapping::memfd(c"test", 4).unwrap();
    seal(&descriptor).unwrap();
    owner.words()[0].store(7, Ordering::Release);
    let read_only = reopen_read_only(&descriptor).unwrap();
    let reader = Mapping::from_descriptor(read_only.as_fd(), ReadOnly).unwrap();
    assert_eq!(reader.words()[0].load(Ordering::Acquire), 7);
    assert!(Mapping::from_descriptor(read_only.as_fd(), Writable).is_err());
    assert!(Mapping::from_descriptor(descriptor.as_fd(), Writable).is_err());
    let path = format!("/proc/self/fd/{}", read_only.as_raw_fd());
    let mut reopened = OpenOptions::new().write(true).open(path).unwrap();
    assert!(reopened.write_all(&[1; 8]).is_err());
    assert_eq!(reader.words()[0].load(Ordering::Acquire), 7);
}
