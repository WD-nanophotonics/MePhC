from __future__ import annotations

import copy
import json
from pathlib import Path

import validate_r15


def reject(value, label):
    try:
        validate_r15.check_contract(value)
    except AssertionError:
        return
    raise AssertionError(f"negative fixture accepted: {label}")


def main():
    c = json.loads((Path(__file__).with_name("authoritative_contract.json")).read_text(encoding="utf-8"))
    bad_ref = copy.deepcopy(c); bad_ref["starting_refs"]["MePhC"] = "deadbeef"; reject(bad_ref, "wrong starting ref")
    bad_h = copy.deepcopy(c); bad_h["magnitude_ladder"]["fresh_exact"] = [0.006, 0.015]; reject(bad_h, "extra fresh magnitude")
    bad_zero = copy.deepcopy(c); bad_zero["scientific_terminal_states"].append("CLOSED_QUADRATIC_ZERO_SUPPORTED"); reject(bad_zero, "zero terminal")
    bad_calls = copy.deepcopy(c); bad_calls["fresh_matrix"]["expected_total_fresh_calls"] = 113; reject(bad_calls, "call count mutation")
    print("R15_NEGATIVE_FIXTURES_PASS 4")


if __name__ == "__main__":
    main()
