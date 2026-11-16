use rapidhash::v3::{RapidSecrets, rapidhash_v3_seeded};

const SECRETS: RapidSecrets = RapidSecrets::seed(0x9e37_79b9_7f4a_7c15);

fn seeded(seed: u64) -> RapidSecrets {
    RapidSecrets { seed, ..SECRETS }
}

pub(crate) fn key(namespace: u64, identity: &[u8], shape: &[u8]) -> u64 {
    let identity_hash = rapidhash_v3_seeded(identity, &seeded(SECRETS.seed ^ namespace));
    rapidhash_v3_seeded(shape, &seeded(identity_hash))
}

#[cfg(test)]
mod tests;
