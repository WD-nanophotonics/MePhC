# MePhC Affine Architecture R3.1 Corrective Evidence

This directory is the immutable evidence bundle for the R3.1 corrective task.
It validates affine motif placement, tracked reciprocal landmark selection, and
real low-resolution production-entry MPB smokes. It does not contain scientific
records or images.

## Scope

- MePhC entry: `24e29d9c9c6ceae979e1a81953c4f54853f98808`
- TriLatt entry: `df2cdf4fd70e741e1a8901a9274a0b0e42b1e737`
- SqrLatt hold: `8a1e4534a48e01a83996fb199ccd55e0983e72b2`
- MePhC final production ref: `d613b2bc188e0bdcfa7abc71cd23caa5a0326f1f`
- TriLatt final production ref: `59d005693a8f86e110686681a610952dc817803d`
- SqrLatt remains unchanged at `8a1e4534a48e01a83996fb199ccd55e0983e72b2`

## Results

| Gate | Result |
|---|---|
| Affine motif centers and rigid local polygons | PASS |
| Identity legacy K and nonidentity `tracked_K1` | PASS |
| Real band/Berry/EFS/frequency MPB entries | PASS |
| TriLatt deformation/current-BZ documentation | PASS |
| MePhC tests | 33 passed |
| TriLatt tests | 28 passed |
| R2/R3 validators | PASS |

Run `python validate_r3_1.py` from this directory to verify all JSON gates,
protected digests, and artifact SHA-256 values.

## Limitations

The implementation covers global affine periodic deformation only. It does not
discover symmetry automatically, implement non-Abelian Berry curvature, or
migrate SqrLatt. R4 is not authorized; independent review is required.
