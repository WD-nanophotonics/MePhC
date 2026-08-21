# E7I.1G C6 exact-q corrective

C6 replaces rounded coordinate cache identity with IEEE-754 round-trip q
identity and separates display labels from physical keys. Every reusable
record must bind requested q, manifest q, and result target_q without allowing
an outer argument to overwrite result provenance.

The existing C4/C5 evidence audit is deliberately fail-closed. It found
32,104 requested/result q mismatches, including 32,092 reused records, and
1,704 old rounded-key collision groups covering 3,442 exact requested records.
The stored evidence therefore cannot be silently relabeled as exact. The
conditional MPB repair gate reports more than the authorized 32 unique points,
so C6 does not launch a broad repair.

The committed compact trace includes exact-q chunk digests, direct evidence
hashes, source/count closures, and a repository component fingerprint map.
reducer_c6.py verifies these bindings before the existing R64-sentinel-median
scaled replay. The numerical replay remains stable relative to C5, but the
physical seal remains pending because q provenance is not exact.

Run tests from this directory with the canonical mp environment:

<canonical mp environment> -m unittest discover -s tests -v

C6 is sandbox-only. Do not promote main or begin wider physics while the exact
q provenance mismatch remains unresolved.
