use super::*;

impl<M: Words> Writer<M> {
    pub(crate) fn snapshot_copy(&self, block: Block) -> Option<Vec<u8>> {
        let snapshot = self.snapshot(block)?;
        let mut copy = vec![0; snapshot.length];
        snapshot.copy_into(&mut copy);
        Some(copy)
    }
}
