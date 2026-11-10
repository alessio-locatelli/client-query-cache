use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use super::{Family, Source};

const CAPACITY: usize = 1024;

#[derive(Hash, PartialEq, Eq)]
pub(super) struct Descriptor {
    pub partition: Option<Vec<u8>>,
    pub dependencies: Option<Vec<String>>,
}

#[derive(Clone, Copy)]
pub(super) struct Guard {
    pub query_token: u64,
    pub group: u64,
    pub version: u64,
    pub epoch: u64,
    pub index: u64,
    pub fallback: u64,
}

struct Group {
    namespace: u64,
    descriptor: Arc<Descriptor>,
    version: u64,
    captures: usize,
    // Only current-version rows reserve selective capacity.
    residents: usize,
    sources: HashMap<u64, Source>,
}

impl Group {
    fn invalidate(&mut self, families: &mut HashMap<isize, Family>) {
        self.version += 1;
        self.residents = 0;
        for (slot, source) in std::mem::take(&mut self.sources) {
            Family::unindex(families, source, slot);
        }
    }
}

#[derive(Default)]
struct NamespaceGroups {
    fallback: u64,
    groups: HashSet<u64>,
    partitions: HashMap<Vec<u8>, HashSet<u64>>,
    unpartitioned: HashSet<u64>,
    families: HashMap<isize, Family>,
}

#[derive(Default)]
pub(super) struct Registry {
    nonce: u64,
    groups: HashMap<u64, Group>,
    keys: HashMap<(u64, Arc<Descriptor>), u64>,
    namespaces: HashMap<u64, NamespaceGroups>,
}

impl Registry {
    pub fn sources(&self, namespace: u64) -> Option<&HashMap<isize, Family>> {
        Some(&self.namespaces.get(&namespace)?.families)
    }

    pub fn index_source(&mut self, namespace: u64, group: u64, source: Source, slot: u64) {
        self.groups
            .get_mut(&group)
            .expect("proof group")
            .sources
            .insert(slot, source);
        let groups = self
            .namespaces
            .get_mut(&namespace)
            .expect("proof namespace");
        Family::index(&mut groups.families, source, slot);
    }

    pub fn unindex_source(&mut self, namespace: u64, group: u64, source: Source, slot: u64) {
        let Some(group) = self.groups.get_mut(&group) else {
            return;
        };
        group.sources.remove(&slot);
        if let Some(groups) = self.namespaces.get_mut(&namespace) {
            Family::unindex(&mut groups.families, source, slot);
        }
    }

    pub fn clear_sources(&mut self, namespace: u64) {
        if let Some(groups) = self.namespaces.get_mut(&namespace) {
            groups.families = HashMap::new();
            for id in &groups.groups {
                let group = self.groups.get_mut(id).expect("proof group");
                group.sources = HashMap::new();
                group.version += 1;
                group.residents = 0;
            }
        }
    }
    pub fn is_empty(&self) -> bool {
        self.groups.is_empty()
    }
    pub fn acquire(&mut self, namespace: u64, descriptor: Descriptor) -> Option<(u64, u64, u64)> {
        let key = (namespace, Arc::new(descriptor));
        if let Some(id) = self.keys.get(&key) {
            let group = self.groups.get_mut(id).expect("indexed proof group");
            group.captures += 1;
            return Some((*id, group.version, self.namespaces[&namespace].fallback));
        }
        if self.groups.len() == CAPACITY {
            let obsolete = self.groups.iter().find_map(|(&id, group)| {
                (group.captures == 0 && group.residents == 0).then_some(id)
            })?;
            self.remove(obsolete);
        }
        self.nonce += 1;
        let id = self.nonce;
        let descriptor = key.1.clone();
        let groups = self.namespaces.entry(namespace).or_default();
        groups.groups.insert(id);
        if let Some(partition) = &descriptor.partition {
            groups
                .partitions
                .entry(partition.clone())
                .or_default()
                .insert(id);
        } else {
            groups.unpartitioned.insert(id);
        }
        let fallback = groups.fallback;
        self.keys.insert(key, id);
        self.groups.insert(
            id,
            Group {
                namespace,
                descriptor,
                version: 0,
                captures: 1,
                residents: 0,
                sources: HashMap::new(),
            },
        );
        Some((id, 0, fallback))
    }

    pub fn valid(&self, guard: Guard) -> bool {
        self.groups.get(&guard.group).is_some_and(|group| {
            group.version == guard.version
                && self.namespaces[&group.namespace].fallback == guard.fallback
        })
    }

    pub fn retain_row(&mut self, id: u64) {
        let group = self.groups.get_mut(&id).expect("reserved proof group");
        group.residents += 1;
    }

    pub fn release(&mut self, guard: Guard, capture: bool) {
        let id = guard.group;
        let Some(group) = self.groups.get_mut(&id) else {
            return;
        };
        if capture {
            group.captures -= 1;
        } else if group.version == guard.version {
            group.residents -= 1;
        }
        if group.captures != 0 || group.residents != 0 {
            return;
        }
        self.remove(id);
    }

    fn remove(&mut self, id: u64) {
        let group = self.groups.remove(&id).expect("reclaimed proof group");
        let namespace = self
            .namespaces
            .get_mut(&group.namespace)
            .expect("proof namespace");
        namespace.groups.remove(&id);
        if let Some(partition) = &group.descriptor.partition {
            let groups = namespace
                .partitions
                .get_mut(partition)
                .expect("proof partition");
            groups.remove(&id);
            if groups.is_empty() {
                namespace.partitions.remove(partition);
            }
        } else {
            namespace.unpartitioned.remove(&id);
        }
        if namespace.groups.is_empty() {
            self.namespaces.remove(&group.namespace);
        }
        self.keys.remove(&(group.namespace, group.descriptor));
    }

    pub fn insert(&mut self, namespace: u64, partition: &[u8]) {
        if let Some(groups) = self.namespaces.get_mut(&namespace) {
            for ids in [
                Some(&groups.unpartitioned),
                groups.partitions.get(partition),
            ]
            .into_iter()
            .flatten()
            {
                for id in ids {
                    self.groups
                        .get_mut(id)
                        .expect("indexed partition group")
                        .invalidate(&mut groups.families);
                }
            }
        }
    }

    pub fn unknown(&mut self, namespace: u64) {
        if let Some(groups) = self.namespaces.get_mut(&namespace) {
            groups.fallback += 1;
            groups.families = HashMap::new();
            for id in &groups.groups {
                let group = self.groups.get_mut(id).expect("proof group");
                group.sources = HashMap::new();
                group.version += 1;
                group.residents = 0;
            }
        }
    }

    pub fn update(&mut self, namespace: u64, paths: &[String]) {
        if let Some(groups) = self.namespaces.get_mut(&namespace) {
            for id in &groups.groups {
                let group = self.groups.get_mut(id).expect("indexed namespace group");
                let independent =
                    group
                        .descriptor
                        .dependencies
                        .as_ref()
                        .is_some_and(|dependencies| {
                            !dependencies.iter().any(|dependency| {
                                paths.iter().any(|path| {
                                    path == dependency
                                        || path
                                            .strip_prefix(dependency)
                                            .is_some_and(|suffix| suffix.starts_with('.'))
                                        || dependency
                                            .strip_prefix(path)
                                            .is_some_and(|suffix| suffix.starts_with('.'))
                                })
                            })
                        });
                if !independent {
                    group.invalidate(&mut groups.families);
                }
            }
        }
    }

    pub fn close(&mut self) {
        for namespace in self.namespaces.values_mut() {
            namespace.families = HashMap::new();
        }
        let ids: Vec<_> = self.groups.keys().copied().collect();
        for id in ids {
            let group = self.groups.get_mut(&id).expect("closing proof group");
            group.sources = HashMap::new();
            group.residents = 0;
            if group.captures == 0 {
                self.remove(id);
            }
        }
    }
}
