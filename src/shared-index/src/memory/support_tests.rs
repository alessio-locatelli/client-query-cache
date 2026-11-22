use super::{AtomicU64, Words};

impl Words for [AtomicU64] {
    fn words(&self) -> &[AtomicU64] {
        self
    }
}

pub(crate) fn zeroed(words: usize) -> std::sync::Arc<[AtomicU64]> {
    (0..words).map(|_| AtomicU64::new(0)).collect()
}
