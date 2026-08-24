import ast
import json
from pathlib import Path
import subprocess
import sys

from audit.infrastructure.native_lifecycle_controller import measure_native_child_exit, scan_native_child_processes


def test_controller_and_parent_runtime_are_solver_free_at_import():
    path = Path(__file__).parents[1] / "audit" / "infrastructure" / "native_lifecycle_controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any("meep" in name.lower() or "mpb" in name.lower() for name in imported)


def test_process_measurement_is_derived_after_fake_worker_exit():
    process = subprocess.Popen([sys.executable, "-c", "print('fake-worker')"], stdout=subprocess.PIPE, text=True)
    process.communicate(timeout=10)
    measurement = measure_native_child_exit(process.pid, "fake_sample")
    assert measurement["direct_pid_gone"] is True
    assert measurement["orphan_count"] == 0


def test_process_table_scan_is_deterministic_for_no_native_children():
    assert scan_native_child_processes("sample_that_cannot_exist") == []
