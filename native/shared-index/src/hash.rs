const SEED: u64 = 0x9e37_79b9_7f4a_7c15;
const MULTIPLIER: u64 = 0x517c_c1b7_2722_0a95;
const FINISH: u64 = 0xff51_afd7_ed55_8ccd;

fn mix(state: u64, word: u64) -> u64 {
    (state.rotate_left(5) ^ word).wrapping_mul(MULTIPLIER)
}

fn mix_bytes(mut state: u64, bytes: &[u8]) -> u64 {
    for chunk in bytes.chunks(8) {
        let mut word = [0_u8; 8];
        word[..chunk.len()].copy_from_slice(chunk);
        state = mix(state, u64::from_le_bytes(word));
    }
    mix(state, bytes.len() as u64)
}

pub(crate) fn key(namespace: u64, identity: &[u8], shape: &[u8]) -> u64 {
    let mut state = mix(SEED, namespace);
    state = mix_bytes(state, identity);
    state = mix_bytes(state, shape);
    state ^= state >> 33;
    state = state.wrapping_mul(FINISH);
    state ^ (state >> 33)
}

#[cfg(test)]
mod tests;
