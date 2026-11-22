use super::key;

const KNOWN_KEY: u64 = 0x61c8_a333_db8d_0639;

#[test]
fn separates_identity_and_shape_boundaries() {
    for (identity, shape) in [(&b"a"[..], &b"bc"[..]), (b"", b"abc"), (b"abc", b"")] {
        assert_ne!(key(0, b"ab", b"c"), key(0, identity, shape));
    }
}

#[test]
fn separates_namespaces() {
    assert_ne!(key(0, b"a", b"b"), key(1, b"a", b"b"));
}

#[test]
fn keeps_the_published_mapping_of_this_layout_version() {
    assert_eq!(key(1, b"identity", b"find_one"), KNOWN_KEY);
}
