use super::*;

const TTL_NS: u64 = 100;
const CAPACITY: usize = 2;

fn names(collection: &str) -> Names {
    (Arc::from("database"), Arc::from(collection))
}

fn probes() -> Probes {
    Probes::new(TTL_NS)
}

#[test]
fn a_refreshed_probe_expires_after_older_probes() {
    let mut probes = probes();
    let first = probes.begin(names("first"), true, CAPACITY, 0).unwrap();
    let second = probes.begin(names("second"), true, CAPACITY, 10).unwrap();
    assert_eq!(probes.begin(names("third"), true, CAPACITY, 20), None);
    assert_eq!(
        probes.begin(names("first"), true, CAPACITY, 60),
        Some(first)
    );
    let between = 10 + TTL_NS + 5;
    assert!(
        probes
            .begin(names("third"), true, CAPACITY, between)
            .is_some()
    );
    assert!(probes.active(&names("first"), first, between));
    assert!(!probes.active(&names("second"), second, between));
}

#[test]
fn a_probe_expires_at_its_ttl() {
    let mut probes = probes();
    let token = probes.begin(names("first"), true, CAPACITY, 0).unwrap();
    assert!(probes.active(&names("first"), token, TTL_NS - 1));
    assert!(!probes.active(&names("first"), token, TTL_NS));
}

#[test]
fn a_probe_stays_reserved_until_every_reference_finishes() {
    let mut probes = probes();
    let token = probes.begin(names("first"), true, 1, 0).unwrap();
    assert_eq!(probes.begin(names("first"), true, 1, 1), Some(token));
    probes.finish(&names("first"), token, 2);
    assert!(probes.active(&names("first"), token, 3));
    assert_eq!(probes.begin(names("second"), true, 1, 4), None);
    probes.finish(&names("first"), token, 5);
    assert!(!probes.active(&names("first"), token, 6));
    assert!(probes.begin(names("second"), true, 1, 7).is_some());
}

#[test]
fn stale_tokens_neither_finish_nor_confirm_a_newer_probe() {
    let mut probes = probes();
    let stale = probes.begin(names("first"), true, CAPACITY, 0).unwrap();
    let current = probes
        .begin(names("first"), true, CAPACITY, TTL_NS)
        .unwrap();
    assert_ne!(stale, current);
    probes.finish(&names("first"), stale, TTL_NS + 1);
    assert!(!probes.active(&names("first"), stale, TTL_NS + 2));
    assert!(probes.active(&names("first"), current, TTL_NS + 2));
}

#[test]
fn inadmissible_probes_are_refused() {
    let mut probes = probes();
    assert_eq!(probes.begin(names("first"), false, CAPACITY, 0), None);
    assert!(probes.begin(names("first"), true, 1, 1).is_some());
}

#[test]
fn invalidation_releases_probe_capacity() {
    let mut probes = probes();
    let first = probes.begin(names("first"), true, CAPACITY, 0).unwrap();
    let other = (Arc::from("other"), Arc::from("first"));
    let foreign = probes.begin(other.clone(), true, CAPACITY, 0).unwrap();
    probes.invalidate(&names("first"));
    assert!(!probes.active(&names("first"), first, 1));
    let second = probes.begin(names("second"), true, CAPACITY, 1).unwrap();
    probes.invalidate_database("database");
    assert!(!probes.active(&names("second"), second, 2));
    assert!(probes.active(&other, foreign, 2));
    probes.clear();
    assert!(!probes.active(&other, foreign, 3));
}
