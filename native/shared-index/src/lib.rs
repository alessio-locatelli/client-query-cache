// Loom builds omit the Python consumers and OS-backed modules. Production linting
// enables `python` and retains all dead-code and unused-import diagnostics.
#![cfg_attr(
    any(loom, all(test, not(feature = "python"))),
    allow(
        dead_code,
        unused_imports,
        reason = "native harnesses omit Python consumers; Loom also omits OS-backed modules"
    )
)]

#[cfg(not(loom))]
mod clock;
#[cfg(not(loom))]
mod echo;
mod frames;
mod hash;
mod index;
#[cfg(all(feature = "python", not(loom)))]
mod key_encoder;
#[cfg(all(feature = "local-cache-prototype", not(loom)))]
mod local_spike;
mod memory;
#[cfg(all(feature = "python", not(loom)))]
mod python;
#[cfg(not(loom))]
mod relay;
mod ring;
mod sync;
