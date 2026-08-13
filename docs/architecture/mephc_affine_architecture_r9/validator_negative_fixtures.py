from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("validate_r9", ROOT / "validate_r9.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def mutate(name, mutation):
    with tempfile.TemporaryDirectory(prefix="r9-negative-") as directory:
        target = Path(directory) / ROOT.name
        shutil.copytree(ROOT, target)
        path = target / name
        data = json.loads(path.read_text(encoding="utf-8"))
        mutation(data)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        old_root = validator.ROOT
        validator.ROOT = target
        try:
            validator.validate_bundle(check_git=False)
        except validator.ValidationError:
            return True
        finally:
            validator.ROOT = old_root
        return False


def drop_channel(data):
    data["20"] = data["20"][:-1]


def adaptive_amplitude(data):
    data["resolutions"]["40"]["0.03"] = data["resolutions"]["40"].pop("0.02")


def tolerance(data):
    data["fresh_calls"][0]["solver_tolerance"] = 1e-6


def fake_cubic(data):
    data["cubic_support_count"] = 2
    data["terminal_state"] = "CLOSED_CUBIC_ODD_RESPONSE_SUPPORTED"


def selected_subset(data):
    data["40"] = data["40"][:-1]


def unauthorized_48(data):
    data["resolution_above_48_ran"] = True


def over_48(data):
    data["fresh_calls"][0]["resolution"] = 49


def trilatt_call(data):
    data["fresh_mpb_solver_calls"] = 1


def mutate_r8(data):
    data["resolved_count"] = 1


def post_seal_semantic(data):
    data["scientific_terminal_state"] = "CLOSED_LINEAR_ODD_RESPONSE_SUPPORTED"


cases = {
    "dropped_q_band_channel": ("response_by_resolution_and_amplitude.json", drop_channel),
    "adaptive_amplitude": ("raw_response_spectra.json", adaptive_amplitude),
    "changed_solver_tolerance": ("solver_execution.json", tolerance),
    "fake_cubic_classification": ("mechanism_adjudication.json", fake_cubic),
    "response_selected_subset": ("response_by_resolution_and_amplitude.json", selected_subset),
    "unauthorized_48_run": ("solver_execution.json", unauthorized_48),
    "resolution_above_48": ("solver_execution.json", over_48),
    "fresh_trilatt_call": ("trilatt_hold.json", trilatt_call),
    "mutated_r8_protected_artifact": ("r8_inheritance.json", mutate_r8),
    "post_seal_semantic": ("completion.json", post_seal_semantic),
}
results = {name: mutate(filename, fn) for name, (filename, fn) in cases.items()}
if not all(results.values()):
    raise SystemExit(json.dumps(results, sort_keys=True))
print(json.dumps({"status": "PASS_R9_NEGATIVE_FIXTURES", "cases": results}, sort_keys=True))
