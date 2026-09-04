"""M48R1 recovery entrypoint delegating to the corrected solver-free analysis."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SOURCE = Path(__file__).with_name("m48_seven_resolution_mixed_family_mechanism_localization.py")
SPEC = importlib.util.spec_from_file_location("m48r1_corrected_impl", SOURCE)
assert SPEC and SPEC.loader
implementation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(implementation)


def main() -> int:
    return implementation.main()


if __name__ == "__main__":
    raise SystemExit(main())
