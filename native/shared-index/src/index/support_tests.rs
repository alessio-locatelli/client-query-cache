use super::*;

impl<M: Words> Index<M> {
    pub(crate) fn snapshot(&self, block: Block) -> Option<Vec<u8>> {
        let length = self.snapshot_length(block)?;
        let mut copy = vec![0; length];
        self.snapshot_into(block, &mut copy).then_some(copy)
    }
}
