use super::*;

const EMPTY_DOCUMENT: [u8; 5] = [5, 0, 0, 0, 0];

fn envelope(document: &[u8]) -> Vec<u8> {
    let total = i32::try_from(document.len() + 8).unwrap();
    let mut bytes = total.to_le_bytes().to_vec();
    bytes.extend_from_slice(&DOCUMENT_ELEMENT);
    bytes.extend_from_slice(document);
    bytes.push(0);
    bytes
}

fn document(field: u8) -> Vec<u8> {
    vec![12, 0, 0, 0, 0x08, field, 0, 1, 0, 0, 0, 0]
}

#[test]
fn an_empty_array_is_a_complete_envelope() {
    let mut builder = ArrayBuilder::default();
    assert_eq!(
        builder.finish(),
        [13, 0, 0, 0, 0x04, b'v', 0, 5, 0, 0, 0, 0, 0]
    );
}

#[test]
fn documents_are_framed_with_decimal_indexes() {
    let mut builder = ArrayBuilder::default();
    assert_eq!(builder.append(&envelope(&EMPTY_DOCUMENT), 5), Ok(true));
    assert_eq!(builder.retained(), 5);
    assert_eq!(
        builder.finish(),
        [
            21, 0, 0, 0, 0x04, b'v', 0, 13, 0, 0, 0, 0x03, b'0', 0, 5, 0, 0, 0, 0, 0, 0
        ]
    );
    assert_eq!(builder.retained(), 0);
}

#[test]
fn index_width_grows_at_each_power_of_ten() {
    let mut builder = ArrayBuilder::default();
    for _ in 0..101 {
        assert_eq!(
            builder.append(&envelope(&EMPTY_DOCUMENT), usize::MAX),
            Ok(true)
        );
    }
    let bytes = builder.finish();
    let element = |key: &[u8]| {
        let mut element = vec![0x03];
        element.extend_from_slice(key);
        element.push(0);
        element.extend_from_slice(&EMPTY_DOCUMENT);
        element
    };
    let expected: Vec<u8> = (0..101)
        .flat_map(|index: u32| element(index.to_string().as_bytes()))
        .collect();
    assert_eq!(&bytes[PREFIX..bytes.len() - TERMINATORS], expected);
    assert_eq!(length(&bytes), Some(bytes.len()));
    assert_eq!(length(&bytes[7..]), Some(bytes.len() - 8));
}

#[test]
fn a_document_beyond_the_retained_limit_is_refused_without_change() {
    let mut builder = ArrayBuilder::default();
    let first = document(b'a');
    assert_eq!(builder.append(&envelope(&first), 12), Ok(true));
    assert_eq!(builder.append(&envelope(&document(b'b')), 23), Ok(false));
    assert_eq!(builder.retained(), 12);
    let bytes = builder.finish();
    assert_eq!(&bytes[PREFIX + 3..bytes.len() - TERMINATORS], first);
}

#[test]
fn an_exact_retained_limit_is_admitted() {
    let mut builder = ArrayBuilder::default();
    assert_eq!(builder.append(&envelope(&document(b'a')), 12), Ok(true));
    assert_eq!(builder.append(&envelope(&document(b'b')), 24), Ok(true));
    assert_eq!(builder.retained(), 24);
}

#[test]
fn malformed_envelopes_are_rejected() {
    let valid = envelope(&document(b'a'));
    let mut wrong_type = valid.clone();
    wrong_type[4] = 0x04;
    let mut wrong_name = valid.clone();
    wrong_name[5] = b'w';
    let mut wrong_length = valid.clone();
    wrong_length[0] += 1;
    let mut wrong_inner_length = valid.clone();
    wrong_inner_length[7] += 1;
    let mut unterminated = valid.clone();
    unterminated[valid.len() - 2] = 1;
    let mut negative = valid.clone();
    negative[3] = 0x80;
    for malformed in [
        valid[..12].to_vec(),
        wrong_type,
        wrong_name,
        wrong_length,
        wrong_inner_length,
        unterminated,
        negative,
        [valid.as_slice(), &[1]].concat(),
    ] {
        let mut builder = ArrayBuilder::default();
        assert_eq!(
            builder.append(&malformed, usize::MAX),
            Err(AppendError::Malformed)
        );
        assert_eq!(builder.retained(), 0);
    }
}

#[test]
fn growth_beyond_the_bson_limit_overflows() {
    assert_eq!(grown(MAXIMUM_BYTES - 10, 1, 5), Some(MAXIMUM_BYTES));
    assert_eq!(grown(MAXIMUM_BYTES - 10, 1, 6), None);
    assert_eq!(grown(usize::MAX - 1, 1, 0), None);
}

#[test]
fn clearing_releases_the_buffer() {
    let mut builder = ArrayBuilder::default();
    assert_eq!(
        builder.append(&envelope(&document(b'a')), usize::MAX),
        Ok(true)
    );
    builder.clear();
    assert_eq!(builder.retained(), 0);
    assert_eq!(builder.bytes.capacity(), 0);
    assert_eq!(builder.finish().len(), MINIMUM_ENVELOPE);
}
