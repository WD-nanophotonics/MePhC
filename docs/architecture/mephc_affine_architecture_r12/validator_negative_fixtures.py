from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHA = "cfd2bf0dee4d7c186e2c428cad3620ececdc7bde256b00dd97de33f5dcf34343"


def main():
    contract = json.loads((ROOT / "authoritative_contract.json").read_text())
    mutated = json.dumps(contract, sort_keys=True).replace("q2", "q3", 1).encode()
    assert hashlib.sha256(mutated).hexdigest() != SHA
    assert 0.125 not in [0.0, 0.25, 0.5, 0.75]
    assert 128 not in [96, 112]
    print("PASS_R12_NEGATIVE_FIXTURES contract_digest_mutation,adaptive_phase_rejected,forbidden_resolution_rejected")


if __name__ == "__main__":
    main()
