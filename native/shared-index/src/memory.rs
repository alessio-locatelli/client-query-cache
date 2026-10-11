use crate::sync::AtomicU64;

pub(crate) const WORD_BYTES: usize = 8;

pub(crate) trait Words {
    fn words(&self) -> &[AtomicU64];
}

impl<T: Words + ?Sized> Words for std::sync::Arc<T> {
    fn words(&self) -> &[AtomicU64] {
        (**self).words()
    }
}

impl Words for [AtomicU64] {
    fn words(&self) -> &[AtomicU64] {
        self
    }
}

#[cfg(test)]
pub(crate) fn zeroed(words: usize) -> std::sync::Arc<[AtomicU64]> {
    (0..words).map(|_| AtomicU64::new(0)).collect()
}

#[cfg(not(loom))]
pub(crate) use mapping::{Mapping, ReadOnly, Writable};

#[cfg(not(loom))]
mod mapping {
    use std::ffi::CStr;
    use std::io;
    use std::os::fd::{AsRawFd, BorrowedFd, FromRawFd, OwnedFd};
    use std::ptr::NonNull;

    use super::{WORD_BYTES, Words};
    use crate::sync::AtomicU64;

    #[derive(Clone, Copy, PartialEq, Eq)]
    pub(crate) enum Access {
        ReadOnly,
        Writable,
    }

    pub(crate) use Access::{ReadOnly, Writable};

    pub(crate) struct Mapping {
        address: NonNull<libc::c_void>,
        bytes: usize,
    }

    unsafe impl Send for Mapping {}
    unsafe impl Sync for Mapping {}

    fn checked(result: libc::c_int) -> io::Result<libc::c_int> {
        if result < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(result)
        }
    }

    fn byte_length(words: usize) -> io::Result<usize> {
        words
            .checked_mul(WORD_BYTES)
            .filter(|bytes| *bytes > 0)
            .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))
    }

    impl Mapping {
        fn map(
            bytes: usize,
            access: Access,
            flags: libc::c_int,
            fd: libc::c_int,
        ) -> io::Result<Self> {
            let protection = match access {
                ReadOnly => libc::PROT_READ,
                Writable => libc::PROT_READ | libc::PROT_WRITE,
            };
            let address =
                unsafe { libc::mmap(std::ptr::null_mut(), bytes, protection, flags, fd, 0) };
            if address == libc::MAP_FAILED {
                return Err(io::Error::last_os_error());
            }
            let address = NonNull::new(address).ok_or_else(io::Error::last_os_error)?;
            Ok(Self { address, bytes })
        }

        pub(crate) fn memfd(name: &CStr, words: usize) -> io::Result<(Self, OwnedFd)> {
            let bytes = byte_length(words)?;
            let fd = checked(unsafe {
                libc::memfd_create(name.as_ptr(), libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING)
            })?;
            let fd = unsafe { OwnedFd::from_raw_fd(fd) };
            let length = libc::off_t::try_from(bytes)
                .map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
            checked(unsafe { libc::ftruncate(fd.as_raw_fd(), length) })?;
            let mapping = Self::map(bytes, Writable, libc::MAP_SHARED, fd.as_raw_fd())?;
            Ok((mapping, fd))
        }

        pub(crate) fn from_descriptor(fd: BorrowedFd<'_>, access: Access) -> io::Result<Self> {
            let mut status = unsafe { std::mem::zeroed::<libc::stat>() };
            checked(unsafe { libc::fstat(fd.as_raw_fd(), &raw mut status) })?;
            let bytes = usize::try_from(status.st_size)
                .ok()
                .filter(|bytes| *bytes > 0 && bytes % WORD_BYTES == 0)
                .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidData))?;
            Self::map(bytes, access, libc::MAP_SHARED, fd.as_raw_fd())
        }
    }

    pub(crate) fn seal(fd: &OwnedFd) -> io::Result<()> {
        let seals =
            libc::F_SEAL_FUTURE_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;
        checked(unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_ADD_SEALS, seals) }).map(drop)
    }

    pub(crate) fn reopen_read_only(fd: &OwnedFd) -> io::Result<OwnedFd> {
        let path = format!("/proc/self/fd/{}\0", fd.as_raw_fd());
        let reopened =
            checked(unsafe { libc::open(path.as_ptr().cast(), libc::O_RDONLY | libc::O_CLOEXEC) })?;
        Ok(unsafe { OwnedFd::from_raw_fd(reopened) })
    }

    impl Words for Mapping {
        fn words(&self) -> &[AtomicU64] {
            unsafe {
                std::slice::from_raw_parts(
                    self.address.as_ptr().cast::<AtomicU64>(),
                    self.bytes / WORD_BYTES,
                )
            }
        }
    }

    impl Drop for Mapping {
        fn drop(&mut self) {
            unsafe {
                libc::munmap(self.address.as_ptr(), self.bytes);
            }
        }
    }
}

#[cfg(not(loom))]
pub(crate) use mapping::{reopen_read_only, seal};

#[cfg(all(test, not(loom)))]
mod tests {
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
}
