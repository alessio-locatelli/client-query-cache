use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

pub(crate) type Names = (Arc<str>, Arc<str>);

struct Probe {
    token: u64,
    active: usize,
    expires: u64,
    sequence: u64,
}

pub(crate) struct Probes {
    ttl_ns: u64,
    entries: HashMap<Names, Probe>,
    order: BTreeMap<u64, Names>,
    sequence: u64,
    next_token: u64,
}

impl Probes {
    pub(crate) fn new(ttl_ns: u64) -> Self {
        Self {
            ttl_ns,
            entries: HashMap::new(),
            order: BTreeMap::new(),
            sequence: 0,
            next_token: 0,
        }
    }

    fn expire(&mut self, now: u64) {
        while let Some((&sequence, names)) = self.order.first_key_value() {
            if self.entries[names].expires > now {
                return;
            }
            let names = self.order.remove(&sequence).expect("ordered probe");
            self.entries.remove(&names);
        }
    }

    fn insert(&mut self, names: Names, mut probe: Probe) -> u64 {
        self.sequence += 1;
        probe.sequence = self.sequence;
        self.order.insert(self.sequence, names.clone());
        let token = probe.token;
        self.entries.insert(names, probe);
        token
    }

    pub(crate) fn begin(
        &mut self,
        names: Names,
        admissible: bool,
        capacity: usize,
        now: u64,
    ) -> Option<u64> {
        self.expire(now);
        if !admissible {
            return None;
        }
        let expires = now.saturating_add(self.ttl_ns);
        let probe = if let Some(mut probe) = self.entries.remove(&names) {
            self.order.remove(&probe.sequence);
            probe.active += 1;
            probe.expires = expires;
            probe
        } else {
            if self.entries.len() >= capacity {
                return None;
            }
            let token = self.next_token;
            self.next_token += 1;
            Probe {
                token,
                active: 1,
                expires,
                sequence: 0,
            }
        };
        Some(self.insert(names, probe))
    }

    pub(crate) fn finish(&mut self, names: &Names, token: u64, now: u64) {
        self.expire(now);
        let Some(probe) = self.entries.get_mut(names) else {
            return;
        };
        if probe.token != token {
            return;
        }
        if probe.active == 1 {
            let sequence = probe.sequence;
            self.entries.remove(names);
            self.order.remove(&sequence);
        } else {
            probe.active -= 1;
        }
    }

    pub(crate) fn active(&mut self, names: &Names, token: u64, now: u64) -> bool {
        self.expire(now);
        self.entries
            .get(names)
            .is_some_and(|probe| probe.token == token)
    }

    pub(crate) fn invalidate(&mut self, names: &Names) {
        if let Some(probe) = self.entries.remove(names) {
            self.order.remove(&probe.sequence);
        }
    }

    pub(crate) fn invalidate_database(&mut self, database: &str) {
        let matching: Vec<_> = self
            .entries
            .keys()
            .filter(|names| names.0.as_ref() == database)
            .cloned()
            .collect();
        for names in matching {
            self.invalidate(&names);
        }
    }

    pub(crate) fn clear(&mut self) {
        self.entries.clear();
        self.order.clear();
    }
}
