from __future__ import annotations

import importlib
import json
import sys


def environment_report() -> dict:
    report = {"python": sys.executable, "python_version": sys.version.split()[0], "modules": {}}
    for name in ("mephc", "meep", "numpy", "scipy", "matplotlib", "tkinter"):
        try:
            module = importlib.import_module(name)
            report["modules"][name] = {
                "ok": True,
                "path": getattr(module, "__file__", None),
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:
            report["modules"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    report["ok"] = all(item["ok"] for item in report["modules"].values())
    return report


def main() -> int:
    report = environment_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
