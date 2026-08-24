"""Audited public C2 representation probe entry point."""
from __future__ import annotations
from audit.e9f import run_e9f_c1_rp2_c2_impl as _impl
from audit.e9f.run_e9f_c1_rp2_c2_impl import *
main = _impl.main
if __name__ == "__main__":
    raise SystemExit(main())
