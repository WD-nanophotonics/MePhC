#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from validate_r20 import validate_payload

ROOT = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix="r20-negative-") as tmp:
        target = Path(tmp) / "bundle"
        target.mkdir()
        for source in ROOT.iterdir():
            if source.is_file() and source.name not in {"artifact_manifest.json", "integrity.json", "completion.json"}:
                (target / source.name).write_bytes(source.read_bytes())
        mechanism_path = target / "mechanism_adjudication.json"
        mechanism = json.loads(mechanism_path.read_text())
        mechanism["scientific_terminal_state"] = "INVALID_NEGATIVE_TERMINAL"
        mechanism_path.write_text(json.dumps(mechanism) + "\n")
        bad_terminal, _ = validate_payload(target)
        contract_path = target / "authoritative_contract.json"
        contract = json.loads(contract_path.read_text())
        contract["starting_refs"]["MePhC"] = "bad"
        contract_path.write_text(json.dumps(contract) + "\n")
        bad_contract, _ = validate_payload(target)
    result = {"invalid_terminal_rejected": not bad_terminal, "invalid_contract_rejected": not bad_contract}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if all(result.values()) else 1)


if __name__ == "__main__":
    main()
