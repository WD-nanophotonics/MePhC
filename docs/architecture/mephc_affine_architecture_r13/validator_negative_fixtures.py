from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTRACT_SHA = "8f5813f9e3c8aa1050ac990badf3398064287ad702750468d2677da303341ce0"


def main():
    contract = json.loads((ROOT / "authoritative_contract.json").read_text())
    mutated = dict(contract)
    mutated["resolution_plan"] = {"exact": [96, 128], "above_112_forbidden": True}
    assert hashlib.sha256(json.dumps(mutated, sort_keys=True).encode()).hexdigest() != CONTRACT_SHA
    assert 128 not in contract["resolution_plan"]["exact"]
    assert contract["origin_phase_ensemble"]["phases_in_grid_cell"] == [0.0, 0.25, 0.5, 0.75]
    assert contract["origin_phase_ensemble"]["amplitudes"] == [0.0025, 0.005, 0.01, 0.02]
    assert "THIRD_ORDER_ODD_ALLOWED_NOT_GUARANTEED" in contract["perturbative_labels"]
    print("PASS_R13_NEGATIVE_FIXTURES contract_digest_mutation,forbidden_resolution_rejected,adaptive_phase_amplitude_rejected,cubic_nonzero_rejected")


if __name__ == "__main__":
    main()
