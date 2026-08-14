from __future__ import annotations

import copy
import json
from pathlib import Path

import validate_r14


def must_reject(mutated: dict, label: str) -> None:
    try:
        validate_r14.check_contract(mutated)
    except AssertionError:
        return
    raise AssertionError(f"negative fixture was accepted: {label}")


def main() -> None:
    contract = json.loads((Path(__file__).with_name("authoritative_contract.json")).read_text(encoding="utf-8"))

    bad_resolution = copy.deepcopy(contract)
    bad_resolution["resolution_plan"]["exact"] = [96, 128]
    must_reject(bad_resolution, "resolution above 112")

    bad_h = copy.deepcopy(contract)
    bad_h["relative_pair"]["h_levels"] = [0.005, 0.015, 0.02]
    must_reject(bad_h, "adaptive or altered h grid")

    bad_terminal = copy.deepcopy(contract)
    bad_terminal["scientific_terminal_states"].append("CLOSED_QUADRATIC_ZERO_SUPPORTED")
    must_reject(bad_terminal, "quadratic-zero terminal")

    bad_d = copy.deepcopy(contract)
    bad_d["benchmark"]["d"][0] += 1e-3
    must_reject(bad_d, "non-zero-sum d")

    print(json.dumps({"validator": "r14-negative-fixtures", "status": "PASS", "fixtures": 4}, sort_keys=True))


if __name__ == "__main__":
    main()
