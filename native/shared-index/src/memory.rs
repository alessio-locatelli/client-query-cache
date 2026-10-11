use std::io;
use std::ptr::NonNull;
use std::sync::Arc;

use crate::sync::AtomicU64;

pub(crate) const WORD_BYTES: usize = 8;

pub(crate) trait Words {
    fn words(&self) -> &[AtomicU64];
}

impl<T: Words + ?Sized> Words for Arc<T> {
    fn words(&self) -> &[AtomicU64] {
        (**self).words()
    }
}

impl Words for [AtomicU64] {
    fn words(&self) -> &[AtomicU64] {
        self
    }
}

pub(crate) struct Mapping {
    address: NonNull<libc::c_void>,
    bytes: usize,
}

unsafe impl Send for Mapping {}
unsafe impl Sync for Mapping {}

impl Mapping {
    pub(crate) fn anonymous_shared(words: usize) -> io::Result<Self> {
        let bytes = words
            .checked_mul(WORD_BYTES)
            .filter(|bytes| *bytes > 0)
            .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))?;
        let address = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                bytes,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED | libc::MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        if address == libc::MAP_FAILED {
            return Err(io::Error::last_os_error());
        }
        let address = NonNull::new(address).ok_or_else(io::Error::last_os_error)?;
        Ok(Self { address, bytes })
    }
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

#[cfg(test)]
pub(crate) fn zeroed(words: usize) -> Arc<[AtomicU64]> {
    (0..words).map(|_| AtomicU64::new(0)).collect()
}
