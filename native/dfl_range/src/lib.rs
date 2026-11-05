//! C ABI for the published Dalek Bulletproofs range-proof implementation.
//! Proves BOTH shifted commitments B+m and B-m, not a one-sided interval.
use bulletproofs::{BulletproofGens, PedersenGens, RangeProof};
use curve25519_dalek::{ristretto::{CompressedRistretto, RistrettoPoint}, scalar::Scalar};
use merlin::Transcript;
use rand_core::OsRng;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::HashMap, ffi::{CStr, CString}, os::raw::c_char, sync::{Mutex, OnceLock}};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    op: String,
    bound: Option<u64>, bits: Option<usize>, context: Option<String>,
    values: Option<Vec<i64>>, blindings: Option<Vec<String>>,
    commitments: Option<Vec<String>>, proof: Option<String>,
}
static GENERATORS: OnceLock<Mutex<HashMap<(usize, usize), BulletproofGens>>> = OnceLock::new();
fn bytes32(value: &str) -> Result<[u8;32], ()> { hex::decode(value).map_err(|_|())?.try_into().map_err(|_|()) }
fn execute(raw: &str) -> Result<Value, ()> {
    if raw.len()>4*1024*1024 {return Err(())}
    let request: Request=serde_json::from_str(raw).map_err(|_|())?;
    let pc=PedersenGens::default();
    if request.op=="info" {return Ok(json!({"ok":true,"library":"bulletproofs-5.0.0","generator":hex::encode(pc.B.compress().as_bytes()),"h":hex::encode(pc.B_blinding.compress().as_bytes())}))}
    let bound=request.bound.ok_or(())?; let bits=request.bits.ok_or(())?;
    if ![8,16,32].contains(&bits) || bound==0 || bound>(1<<29) || 2*bound >= (1u64<<bits) {return Err(())}
    let context=bytes32(&request.context.ok_or(())?)?;
    let mut transcript=Transcript::new(b"secure-dfl-v6-bounded-ciphertext");
    transcript.append_message(b"context",&context); transcript.append_u64(b"bound",bound);
    transcript.append_u64(b"bits",bits as u64);
    let mut values=Vec::new(); let mut blinds=Vec::new(); let mut commitments=Vec::new();
    if request.op=="prove" {
        let inputs=request.values.ok_or(())?; let randomness=request.blindings.ok_or(())?;
        if inputs.is_empty() || inputs.len()>4096 || inputs.len()!=randomness.len() {return Err(())}
        for (m,encoded) in inputs.iter().zip(randomness.iter()) {
            if m.unsigned_abs()>bound {return Err(())}
            let b=Option::<Scalar>::from(Scalar::from_canonical_bytes(bytes32(encoded)?)).ok_or(())?;
            values.push((bound as i64+*m) as u64); values.push((bound as i64-*m) as u64);
            blinds.push(b); blinds.push(-b);
        }
    } else if request.op=="verify" {
        let points=request.commitments.ok_or(())?;
        if points.is_empty() || points.len()>4096 {return Err(())}
        let shift=Scalar::from(bound)*pc.B;
        for encoded in points {
            let v=CompressedRistretto(bytes32(&encoded)?).decompress().ok_or(())?;
            commitments.push((shift+v).compress()); commitments.push((shift-v).compress());
        }
    } else {return Err(())}
    let actual=if request.op=="prove" {values.len()} else {commitments.len()};
    let padded=actual.next_power_of_two();
    transcript.append_u64(b"actual_values",actual as u64);
    // Padding is publicly fixed to commitment G (value=1, blinding=0).
    if request.op=="prove" {
        values.resize(padded,1); blinds.resize(padded,Scalar::ZERO);
    } else {commitments.resize(padded,pc.B.compress())}
    let mut cache=GENERATORS.get_or_init(||Mutex::new(HashMap::new())).lock().map_err(|_|())?;
    let generators=cache.entry((bits,padded)).or_insert_with(||BulletproofGens::new(bits,padded));
    if request.op=="prove" {
        let (proof,_)=RangeProof::prove_multiple_with_rng(generators,&pc,&mut transcript,&values,&blinds,bits,&mut OsRng).map_err(|_|())?;
        Ok(json!({"ok":true,"proof":hex::encode(proof.to_bytes())}))
    } else {
        let encoded=request.proof.ok_or(())?;
        if encoded.len()>32768 {return Err(())}
        let proof=RangeProof::from_bytes(&hex::decode(encoded).map_err(|_|())?).map_err(|_|())?;
        proof.verify_multiple_with_rng(generators,&pc,&mut transcript,&commitments,bits,&mut OsRng).map_err(|_|())?;
        Ok(json!({"ok":true}))
    }
}
#[no_mangle]
pub unsafe extern "C" fn dfl_range_call(input: *const c_char) -> *mut c_char {
    let result=std::panic::catch_unwind(|| {
        if input.is_null() {return Err(())}
        execute(CStr::from_ptr(input).to_str().map_err(|_|())?)
    });
    let value=match result {Ok(Ok(v))=>v,_=>json!({"ok":false,"error":"range proof rejected"})};
    CString::new(value.to_string()).unwrap().into_raw()
}
#[no_mangle]
pub unsafe extern "C" fn dfl_range_free(pointer: *mut c_char) {
    if !pointer.is_null() {drop(CString::from_raw(pointer))}
}
