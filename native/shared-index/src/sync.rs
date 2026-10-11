#[cfg(loom)]
pub(crate) use loom::sync::atomic::{AtomicU64, Ordering, fence};
#[cfg(not(loom))]
pub(crate) use std::sync::atomic::{AtomicU64, Ordering, fence};
