use super::key;

#[test]
fn separates_identity_and_shape_boundaries() {
    assert_ne!(key(0, b"ab", b"c"), key(0, b"a", b"bc"));
}

#[test]
fn separates_namespaces() {
    assert_ne!(key(0, b"a", b"b"), key(1, b"a", b"b"));
}
