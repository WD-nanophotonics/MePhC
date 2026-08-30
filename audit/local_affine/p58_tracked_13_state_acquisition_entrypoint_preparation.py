"""Prepare and statically validate the reusable thirteen-state entrypoint."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "audit" / "local_affine" / "p2_frozen_13_state_request_graph.json"
TARGET = ROOT / "audit" / "local_affine" / "frozen_13_state_live_acquisition_v2.py"
TARGET_RELATIVE = "audit/local_affine/frozen_13_state_live_acquisition_v2.py"
RESULT_SCHEMA = "mephc-local-affine-p58-tracked-13-state-acquisition-entrypoint-preparation-v1"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_result(value: dict[str, Any]) -> None:
    target = Path(os.environ["MEPHC_RESULT_PATH"])
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_bytes(canonical(value))
    os.replace(temporary, target)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_count() -> int:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    require(isinstance(graph, dict) and graph.get("state_count") == 13 and graph.get("logical_state_count") == 13 and graph.get("unique_state_count") == 13, "FROZEN_STATE_GRAPH_COUNT_INVALID")
    states = graph.get("states")
    require(isinstance(states, list) and len(states) == 13, "FROZEN_STATE_GRAPH_STATE_LIST_INVALID")
    require([item.get("state_id") for item in states] == [f"STATE_{index:02d}" for index in range(1, 14)], "FROZEN_STATE_GRAPH_ORDER_INVALID")
    require(len({item.get("state_id") for item in states}) == 13, "FROZEN_STATE_GRAPH_DUPLICATE")
    return len(states)


def tracked_blob(source_commit: str) -> str:
    result = subprocess.run(["git", "rev-parse", f"{source_commit}:{TARGET_RELATIVE}"], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def static_validate_self() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    direct_solves = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "solve"]
    require(not direct_solves, "P58_VALIDATOR_DIRECT_SOLVE_REACHABLE")


def main() -> int:
    require(TARGET.is_file(), "TARGET_ENTRYPOINT_MISSING")
    target_text = TARGET.read_text(encoding="utf-8")
    compile(target_text, str(TARGET), "exec")
    compile(Path(__file__).read_text(encoding="utf-8"), __file__, "exec")
    static_validate_self()
    require("MEPHC_INPUT_BUNDLE" in target_text and "MEPHC_RESULT_PATH" in target_text, "TARGET_INPUT_RESULT_CHANNEL_MISSING")
    require("BudgetCounter(13, 13)" in target_text and "LocalAffineStateProvider" in target_text, "TARGET_THIRTEEN_STATE_SUPPORT_MISSING")
    require("ImmutableDatasetStore" in target_text and "normalize_json" in target_text, "TARGET_DATASET_NORMALIZATION_MISSING")
    require("MEPHC-LOCALAFFINE-P58" not in target_text, "TARGET_WORK_ORDER_HARDCODED")
    state_count = graph_count()
    source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
    require(isinstance(source_commit, str) and source_commit, "SCIENCE_SOURCE_COMMIT_MISSING")
    blob = tracked_blob(source_commit)
    write_result({
        "schema": RESULT_SCHEMA,
        "work_order_id": "MEPHC-LOCALAFFINE-P58-TRACKED-13-STATE-ACQUISITION-ENTRYPOINT-PREPARATION-20260830-422",
        "target_entrypoint_tracked": True,
        "target_entrypoint_path": TARGET_RELATIVE,
        "target_entrypoint_blob_sha": blob,
        "target_entrypoint_file_sha256": sha256_file(TARGET),
        "post_implementation_source_commit": source_commit,
        "request_graph_state_count": state_count,
        "request_graph_sha256": sha256_file(GRAPH_PATH),
        "validator_compilation_passed": True,
        "target_compilation_passed": True,
        "validator_direct_provider_solve_reachable": False,
        "native_invocation_count": 0,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
        "field_payload_retained": False,
        "status": "PASS",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
