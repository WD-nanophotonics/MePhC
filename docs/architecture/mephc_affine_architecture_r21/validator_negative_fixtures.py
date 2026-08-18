#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from validate_r21 import REQUIRED, validate_payload

ROOT = Path(__file__).resolve().parent


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="r21-negative-") as tmp:
        target = Path(tmp) / "bundle"
        target.mkdir()
        for name in REQUIRED:
            source = ROOT / name
            if source.exists() and name not in {"artifact_manifest.json", "integrity.json", "completion.json"}:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        mechanism = json.loads((target / "mechanism_adjudication.json").read_text())
        mechanism["scientific_terminal_state"] = "INVALID_NEGATIVE_TERMINAL"
        (target / "mechanism_adjudication.json").write_text(json.dumps(mechanism) + "\n")
        bad_terminal, _ = validate_payload(target)
        contract = json.loads((target / "authoritative_contract.json").read_text())
        contract["starting_refs"]["MePhC"] = "bad"
        (target / "authoritative_contract.json").write_text(json.dumps(contract) + "\n")
        bad_contract, _ = validate_payload(target)
    result = {"invalid_terminal_rejected": not bad_terminal, "invalid_contract_rejected": not bad_contract}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if all(result.values()) else 1)


if __name__ == "__main__":
    main()
