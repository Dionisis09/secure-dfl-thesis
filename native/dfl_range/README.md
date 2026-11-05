# Native range-proof bridge

Build with `cargo build --release --locked` in this directory. Set
`DFL_RANGE_LIB` to the resulting shared library (`libdfl_range.so` on Linux,
`libdfl_range.dylib` on macOS, `dfl_range.dll` on Windows with the appropriate
Rust linker/toolchain installed). No prebuilt binary is committed.

The C ABI accepts bounded JSON requests through local memory, calls Dalek's
published Bulletproofs implementation and returns public proofs/results. Private
values/blindings are never passed on a command line or written to files by this
bridge. This is not a claim of complete process-memory zeroization.

The prover and verifier use both shifted commitments for a signed interval;
fixed padding and a domain-separated Merlin transcript bind the exact statement.
Python additionally links the Pedersen commitment to the ElGamal ciphertext.
See [the application design](../../docs/SECURE_PROTOCOL_V6.md) for equations,
trusted-host boundaries and the recorded dependency-maintenance advisory.
