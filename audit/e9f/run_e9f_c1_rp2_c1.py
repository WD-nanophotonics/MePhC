"""Clean audited public entry point for E9F.C1.RP2.C1."""
from __future__ import annotations
from audit.e9f import run_e9f_c1_rp2_c1_impl as _impl
from audit.e9f.run_e9f_c1_rp2_c1_impl import *
main = _impl.main
if __name__ == "__main__":
    raise SystemExit(main())
