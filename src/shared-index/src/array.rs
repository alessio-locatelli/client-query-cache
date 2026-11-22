const ARRAY_ELEMENT: [u8; 3] = [0x04, b'v', 0];
const DOCUMENT_ELEMENT: [u8; 3] = [0x03, b'v', 0];
const PREFIX: usize = 11;
const TERMINATORS: usize = 2;
const MINIMUM_ENVELOPE: usize = 13;
const MAXIMUM_BYTES: usize = i32::MAX as usize;

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum AppendError {
    Malformed,
    Overflow,
}

#[derive(Default)]
pub(crate) struct ArrayBuilder {
    bytes: Vec<u8>,
    count: u64,
    retained: usize,
}

fn length(bytes: &[u8]) -> Option<usize> {
    usize::try_from(i32::from_le_bytes(bytes.get(..4)?.try_into().ok()?)).ok()
}

fn embedded(envelope: &[u8]) -> Option<&[u8]> {
    if envelope.len() < MINIMUM_ENVELOPE
        || envelope[4..7] != DOCUMENT_ELEMENT
        || envelope.last() != Some(&0)
        || length(envelope)? != envelope.len()
    {
        return None;
    }
    let document = &envelope[7..envelope.len() - 1];
    (length(document)? == document.len() && document.last() == Some(&0)).then_some(document)
}

fn decimal(value: u64, digits: &mut [u8; 20]) -> &[u8] {
    let mut start = digits.len();
    let mut remaining = value;
    loop {
        start -= 1;
        digits[start] = b'0' + (remaining % 10) as u8;
        remaining /= 10;
        if remaining == 0 {
            return &digits[start..];
        }
    }
}

fn grown(current: usize, key: usize, document: usize) -> Option<usize> {
    [1, key, 1, document, TERMINATORS]
        .into_iter()
        .try_fold(current, usize::checked_add)
        .filter(|total| *total <= MAXIMUM_BYTES)
}

fn header(bytes: &mut Vec<u8>) {
    bytes.extend_from_slice(&[0; 4]);
    bytes.extend_from_slice(&ARRAY_ELEMENT);
    bytes.extend_from_slice(&[0; 4]);
}

impl ArrayBuilder {
    pub(crate) fn retained(&self) -> usize {
        self.retained
    }

    pub(crate) fn append(&mut self, envelope: &[u8], limit: usize) -> Result<bool, AppendError> {
        let document = embedded(envelope).ok_or(AppendError::Malformed)?;
        let Some(retained) = self
            .retained
            .checked_add(document.len())
            .filter(|retained| *retained <= limit)
        else {
            return Ok(false);
        };
        let mut digits = [0; 20];
        let key = decimal(self.count, &mut digits);
        let current = if self.bytes.is_empty() {
            PREFIX
        } else {
            self.bytes.len()
        };
        let total = grown(current, key.len(), document.len()).ok_or(AppendError::Overflow)?;
        if self.bytes.is_empty() {
            self.bytes.reserve(total);
            header(&mut self.bytes);
        }
        self.bytes.push(0x03);
        self.bytes.extend_from_slice(key);
        self.bytes.push(0);
        self.bytes.extend_from_slice(document);
        self.count += 1;
        self.retained = retained;
        Ok(true)
    }

    pub(crate) fn finish(&mut self) -> Vec<u8> {
        let mut bytes = std::mem::take(&mut self.bytes);
        self.clear();
        if bytes.is_empty() {
            header(&mut bytes);
        }
        bytes.extend_from_slice(&[0; TERMINATORS]);
        let total = i32::try_from(bytes.len()).expect("checked BSON envelope length");
        bytes[..4].copy_from_slice(&total.to_le_bytes());
        bytes[7..PREFIX].copy_from_slice(&(total - 8).to_le_bytes());
        bytes
    }

    pub(crate) fn clear(&mut self) {
        *self = Self::default();
    }
}

#[cfg(all(test, not(loom)))]
mod tests;
