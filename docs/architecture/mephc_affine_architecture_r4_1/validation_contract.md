# Validation Contract

validate_r4_1.py --check-bundle must not import MePhC, invoke Git, inspect
implicit worktree paths, use network services, or invoke MPB. It validates
schemas, immutable R4 digests, manifests, semantic gates, smoke bindings,
portable command text, and real fixture results.

--check-worktrees requires three explicit roots and two explicit MePhC refs.
It computes remote identity, local HEAD, origin/main, containment,
content-clean porcelain-v2 status, protected-path changes, payload parentage,
and the exact two-file seal diff.

Stable diagnostics are prefixed E_ and are asserted by subprocess fixtures.
