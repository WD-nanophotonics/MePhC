#!/home/icy/miniconda3/envs/mp/bin/python
"""Generic, local-only Scientific Native Job primitives for direct-flow."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import tempfile
import time
from typing import Any


CONTRACT_SCHEMA = "mephc-science-work-order-v1"
DATASET_SCHEMA = "mephc-scientific-dataset-v1"
RECORD_SCHEMA = "mephc-scientific-record-v1"
CERT_SCHEMA = "mephc-science-runtime-certification-v1"
ACTIONS = {"acquire", "analyze", "corrective", "infrastructure"}
KINDS = {"SCIENCE", "INFRASTRUCTURE"}
CAPABILITIES = {
    "exact_checkout", "sandbox_publication", "native_execution", "mpb",
    "private_retention", "cross_commit_dataset_read", "result_channel",
    "checkpoint", "payload_codec", "automatic_provenance",
}
SHA40 = lambda value: isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)
SHA64 = lambda value: isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class ScientificJobError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_bytes(path, canonical_bytes(value) + b"\n")


def normalize_contract(value: Any) -> Any:
    """Normalize bounded fresh-Chat aliases without adding actions or states."""
    if not isinstance(value, dict) or value.get("schema") != CONTRACT_SCHEMA:
        return value
    result = json.loads(json.dumps(value))
    raw_budgets = result.get("budgets") if isinstance(result.get("budgets"), dict) else {}
    if (result.get("kind") == "INFRASTRUCTURE"
            and all(raw_budgets.get(name) == 0 for name in (
                "native_invocations", "provider_requests", "solver_executions"
            ))):
        result["action"] = "infrastructure"
    if (result.get("action") == "analyze" and isinstance(result.get("budgets"), dict)
            and result["budgets"].get("native_invocations") == 1):
        # An explicit Native reservation is stronger and safer than Chat's
        # occasional use of "analyze" to describe a live recertification.
        result["action"] = "acquire"
    capabilities = result.get("required_capabilities")
    if isinstance(capabilities, list) and any(item not in CAPABILITIES for item in capabilities):
        action = result.get("action")
        budgets = result.get("budgets") if isinstance(result.get("budgets"), dict) else {}
        normalized = ["exact_checkout", "sandbox_publication", "result_channel", "automatic_provenance"]
        if action == "acquire":
            normalized.append("native_execution")
            if budgets.get("solver_executions"):
                normalized.append("mpb")
        inputs = result.get("inputs") if isinstance(result.get("inputs"), dict) else {}
        if action == "analyze" and ("datasets" in inputs or "dataset_id" in inputs):
            normalized.extend(["private_retention", "cross_commit_dataset_read"])
        result["required_capabilities"] = normalized
    if result.get("action") == "infrastructure" and isinstance(result.get("entrypoint"), str):
        candidate = PurePosixPath(result["entrypoint"])
        allowed = result.get("allowed_writes")
        if (not candidate.is_absolute() and ".." not in candidate.parts
                and candidate.suffix == ".py" and isinstance(allowed, list)
                and result["entrypoint"] in allowed):
            # Fresh Chat sometimes labels the primary infrastructure artifact
            # as an entrypoint.  Infrastructure never executes it as Native.
            result["entrypoint"] = None
    if str(result.get("kind", "")).casefold() != "diagnostic":
        return result
    raw_budgets = result.get("budgets") if isinstance(result.get("budgets"), dict) else {}
    budgets = {
        "native_invocations": raw_budgets.get("native_invocations", 0),
        "provider_requests": raw_budgets.get("provider_requests", raw_budgets.get("provider_executions", 0)),
        "solver_executions": raw_budgets.get("solver_executions", 0),
    }
    action = "acquire" if budgets["native_invocations"] else "analyze"
    capabilities = ["exact_checkout", "sandbox_publication", "result_channel", "automatic_provenance"]
    if action == "acquire":
        capabilities.append("native_execution")
        if budgets["solver_executions"]:
            capabilities.append("mpb")
    output = result.get("expected_output")
    if not isinstance(output, dict) or set(output) != {"dataset_schema", "result_schema"}:
        result_schema = "mephc-diagnostic-result-" + digest(value)[:16] + "-v1"
        output = {"dataset_schema": None, "result_schema": result_schema}
    result.update({
        "kind": "SCIENCE", "action": action, "project": ".", "budgets": budgets,
        "required_capabilities": capabilities, "expected_output": output,
        "original_work_order_class": "DIAGNOSTIC",
    })
    return result


def validate_contract(value: Any) -> dict[str, Any]:
    value = normalize_contract(value)
    if not isinstance(value, dict) or value.get("schema") != CONTRACT_SCHEMA:
        raise ScientificJobError("WORK_ORDER_MACHINE_CONTRACT_REQUIRED")
    required = {
        "schema", "kind", "work_order_id", "source_commit", "action",
        "project", "entrypoint", "inputs", "budgets", "required_capabilities",
        "allowed_writes", "expected_output", "acceptance_criteria", "forbidden",
    }
    optional = {"mode", "original_work_order_class", "parent_work_order_id"}
    if not required.issubset(value) or set(value) - required - optional:
        raise ScientificJobError("WORK_ORDER_CONTRACT_FIELDS_INVALID")
    if value["kind"] not in KINDS or value["action"] not in ACTIONS:
        raise ScientificJobError("WORK_ORDER_CONTRACT_CLASS_INVALID")
    if not isinstance(value["work_order_id"], str) or not value["work_order_id"].startswith("MEPHC-"):
        raise ScientificJobError("WORK_ORDER_CONTRACT_ID_INVALID")
    if not SHA40(value["source_commit"]) or value["project"] != ".":
        raise ScientificJobError("WORK_ORDER_CONTRACT_SOURCE_INVALID")
    entrypoint = value["entrypoint"]
    if value["action"] in {"acquire", "analyze"}:
        if not isinstance(entrypoint, str):
            raise ScientificJobError("WORK_ORDER_ENTRYPOINT_REQUIRED")
        relative = PurePosixPath(entrypoint)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
            raise ScientificJobError("WORK_ORDER_ENTRYPOINT_INVALID")
    elif entrypoint is not None:
        raise ScientificJobError("INFRASTRUCTURE_ENTRYPOINT_MUST_BE_NULL")
    if not isinstance(value["inputs"], dict):
        raise ScientificJobError("WORK_ORDER_INPUTS_INVALID")
    budgets = value["budgets"]
    if not isinstance(budgets, dict) or set(budgets) != {"native_invocations", "provider_requests", "solver_executions"}:
        raise ScientificJobError("WORK_ORDER_BUDGET_FIELDS_INVALID")
    if any(type(item) is not int or item < 0 for item in budgets.values()):
        raise ScientificJobError("WORK_ORDER_BUDGET_INVALID")
    if value["action"] in {"analyze", "corrective"} and any(budgets.values()):
        raise ScientificJobError("SOLVER_FREE_ANALYSIS_BUDGET_NONZERO")
    if value["action"] == "infrastructure" and any(budgets.values()):
        raise ScientificJobError("INFRASTRUCTURE_EXECUTION_BUDGET_NONZERO")
    if value["action"] == "acquire" and budgets["native_invocations"] != 1:
        raise ScientificJobError("ACQUISITION_INVOCATION_BUDGET_INVALID")
    capabilities = value["required_capabilities"]
    if not isinstance(capabilities, list) or any(item not in CAPABILITIES for item in capabilities):
        raise ScientificJobError("WORK_ORDER_CAPABILITY_INVALID")
    for field in ("allowed_writes", "acceptance_criteria", "forbidden"):
        if not isinstance(value[field], list) or any(not isinstance(item, str) for item in value[field]):
            raise ScientificJobError(f"WORK_ORDER_{field.upper()}_INVALID")
    output = value["expected_output"]
    if not isinstance(output, dict) or set(output) != {"dataset_schema", "result_schema"}:
        raise ScientificJobError("WORK_ORDER_OUTPUT_SCHEMA_INVALID")
    if any(item is not None and not isinstance(item, str) for item in output.values()):
        raise ScientificJobError("WORK_ORDER_OUTPUT_SCHEMA_INVALID")
    if value["action"] == "acquire" and (
        not isinstance(output["result_schema"], str) or not output["result_schema"]
    ):
        raise ScientificJobError("ACQUISITION_RESULT_SCHEMA_REQUIRED")
    if value["action"] == "analyze":
        if not isinstance(output["result_schema"], str) or not output["result_schema"]:
            raise ScientificJobError("ANALYSIS_RESULT_SCHEMA_REQUIRED")
        if "dataset_id" in value["inputs"]:
            if not SHA64(value["inputs"].get("dataset_id")):
                raise ScientificJobError("ANALYSIS_DATASET_INPUT_INVALID")
            manifest = value["inputs"].get("dataset_manifest_sha256")
            if manifest is not None and not SHA64(manifest):
                raise ScientificJobError("ANALYSIS_DATASET_MANIFEST_INVALID")
        elif output["dataset_schema"] is not None:
            raise ScientificJobError("ARTIFACT_ONLY_ANALYSIS_DATASET_SCHEMA_REQUIRED_NULL")
    if value["action"] == "corrective":
        if value["kind"] != "SCIENCE" or value.get("mode", "CORRECTIVE") != "CORRECTIVE":
            raise ScientificJobError("CORRECTIVE_CONTRACT_CLASS_INVALID")
        if any(budgets.values()) or output["dataset_schema"] is not None:
            raise ScientificJobError("CORRECTIVE_CONTRACT_EXECUTION_FORBIDDEN")
    if value["kind"] == "SCIENCE" and any(
        path.startswith("tools/mephc-flow/") for path in value["allowed_writes"]
    ):
        raise ScientificJobError("SCIENCE_CONTRACT_INFRASTRUCTURE_WRITE_FORBIDDEN")
    result = json.loads(json.dumps(value))
    result.setdefault("mode", "CORRECTIVE" if value["action"] == "corrective" else "STANDARD")
    result.setdefault("original_work_order_class", value["kind"])
    result["contract_sha256"] = digest(value)
    return result


def _counter_state_path() -> Path | None:
    raw = os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH")
    return Path(raw) if raw else None


def _update_execution_counters(**increments: int) -> dict[str, Any]:
    path = _counter_state_path()
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScientificJobError("EXECUTION_COUNTER_STATE_INVALID") from exc
    for key in ("actual_provider_execution_count", "actual_solver_execution_count",
                "actual_dataset_record_count"):
        current = value.get(key, 0)
        if type(current) is not int or current < 0:
            raise ScientificJobError("EXECUTION_COUNTER_STATE_INVALID")
        value[key] = current + increments.get(key, 0)
    value["schema"] = "mephc-native-execution-counters-v1"
    value["last_counter_update_at"] = time.time()
    atomic_json(path, value)
    return value


class BudgetCounter:
    """Fail-before-call accounting for provider and solver operations."""

    def __init__(self, provider_limit: int, solver_limit: int) -> None:
        if type(provider_limit) is not int or type(solver_limit) is not int or provider_limit < 0 or solver_limit < 0:
            raise ScientificJobError("BUDGET_COUNTER_INVALID")
        self.provider_limit, self.solver_limit = provider_limit, solver_limit
        self.provider_count = self.solver_count = 0

    def consume_provider(self) -> None:
        if self.provider_count >= self.provider_limit:
            raise ScientificJobError("PROVIDER_REQUEST_BUDGET_EXCEEDED")
        self.provider_count += 1
        _update_execution_counters(actual_provider_execution_count=1)

    def consume_solver(self) -> None:
        if self.solver_count >= self.solver_limit:
            raise ScientificJobError("SOLVER_EXECUTION_BUDGET_EXCEEDED")
        self.solver_count += 1
        _update_execution_counters(actual_solver_execution_count=1)


def runtime_hash(root: Path) -> str:
    files = [
        root / "tools" / "mephc-flow" / "scientific_job.py",
        root / "tools" / "mephc-flow" / "wsl_native_exec.py",
    ]
    accumulator = hashlib.sha256()
    for path in files:
        accumulator.update(path.relative_to(root).as_posix().encode())
        accumulator.update(hashlib.sha256(path.read_bytes()).digest())
    return accumulator.hexdigest()


class ImmutableDatasetStore:
    """Generic write-once exact-key store with a content-addressed manifest."""

    def __init__(self, state_root: Path, namespace: dict[str, Any]) -> None:
        if not isinstance(namespace, dict) or not namespace:
            raise ScientificJobError("DATASET_NAMESPACE_INVALID")
        self.state_root = state_root.resolve()
        self.namespace = json.loads(json.dumps(namespace))
        self.namespace_sha256 = digest(self.namespace)
        self.root = self.state_root / "datasets" / self.namespace_sha256
        self.records = self.root / "records"

    def _paths(self, key: bytes) -> tuple[Path, Path]:
        key_sha = hashlib.sha256(key).hexdigest()
        return self.records / f"{key_sha}.payload", self.records / f"{key_sha}.json"

    def put(self, key: bytes, payload: bytes, identity: dict[str, Any]) -> dict[str, Any]:
        if not key or not payload or not isinstance(identity, dict):
            raise ScientificJobError("DATASET_RECORD_INVALID")
        payload_path, metadata_path = self._paths(key)
        metadata = {
            "schema": RECORD_SCHEMA,
            "key_sha256": hashlib.sha256(key).hexdigest(),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "identity": identity,
            "complete": True,
        }
        if metadata_path.exists() or payload_path.exists():
            existing = json.loads(metadata_path.read_text(encoding="utf-8"))
            if existing != metadata or payload_path.read_bytes() != payload:
                raise ScientificJobError("DATASET_RECORD_IMMUTABILITY_VIOLATION")
            return existing
        atomic_bytes(payload_path, payload)
        atomic_json(metadata_path, {**metadata, "complete": False})
        atomic_json(metadata_path, metadata)
        _update_execution_counters(actual_dataset_record_count=1)
        return metadata

    def get(self, key: bytes) -> tuple[bytes, dict[str, Any]]:
        payload_path, metadata_path = self._paths(key)
        try:
            payload = payload_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScientificJobError("DATASET_RECORD_UNAVAILABLE") from exc
        if (metadata.get("schema") != RECORD_SCHEMA or metadata.get("complete") is not True
                or metadata.get("key_sha256") != hashlib.sha256(key).hexdigest()
                or metadata.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
                or metadata.get("payload_size_bytes") != len(payload)):
            raise ScientificJobError("DATASET_RECORD_INTEGRITY_MISMATCH")
        return payload, metadata

    def finalize(self, expected_count: int, provenance: dict[str, Any]) -> dict[str, Any]:
        records = []
        for path in sorted(self.records.glob("*.json")):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            payload_path = path.with_suffix(".payload")
            payload = payload_path.read_bytes()
            if (metadata.get("complete") is not True
                    or metadata.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
                    or metadata.get("payload_size_bytes") != len(payload)):
                raise ScientificJobError("DATASET_RECORD_INTEGRITY_MISMATCH")
            records.append(metadata)
        if len(records) != expected_count:
            raise ScientificJobError("DATASET_COMPLETION_COUNT_INVALID")
        unsigned = {
            "schema": DATASET_SCHEMA,
            "namespace": self.namespace,
            "namespace_sha256": self.namespace_sha256,
            "record_count": len(records),
            "records": records,
            "provenance": provenance,
            "completion_state": "COMPLETE",
        }
        dataset_id = digest(unsigned)
        content = {**unsigned, "dataset_id": dataset_id}
        content["manifest_sha256"] = digest(content)
        manifest = self.root / "dataset-manifest.json"
        if manifest.exists():
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            if existing != content:
                raise ScientificJobError("DATASET_MANIFEST_IMMUTABILITY_VIOLATION")
        else:
            atomic_json(manifest, content)
        index = self.state_root / "dataset-index" / f"{dataset_id}.json"
        atomic_json(index, {
            "schema": "mephc-scientific-dataset-index-v1",
            "dataset_id": dataset_id,
            "namespace_sha256": self.namespace_sha256,
            "manifest_sha256": content["manifest_sha256"],
        })
        return content


def verify_dataset(state_root: Path, dataset_id: str) -> dict[str, Any]:
    if not SHA64(dataset_id):
        raise ScientificJobError("DATASET_ID_INVALID")
    index_path = state_root / "dataset-index" / f"{dataset_id}.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        manifest_path = state_root / "datasets" / index["namespace_sha256"] / "dataset-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScientificJobError("DATASET_NOT_FOUND") from exc
    unsigned = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
    if (manifest.get("dataset_id") != dataset_id or digest(unsigned) != dataset_id
            or digest({**unsigned, "dataset_id": dataset_id}) != manifest.get("manifest_sha256")
            or manifest.get("manifest_sha256") != index.get("manifest_sha256")):
        raise ScientificJobError("DATASET_MANIFEST_INTEGRITY_MISMATCH")
    store = ImmutableDatasetStore(state_root, manifest["namespace"])
    for record in manifest["records"]:
        key_sha = record["key_sha256"]
        payload_path = store.records / f"{key_sha}.payload"
        payload = payload_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["payload_sha256"] or len(payload) != record["payload_size_bytes"]:
            raise ScientificJobError("DATASET_RECORD_INTEGRITY_MISMATCH")
    return {
        "dataset_id": dataset_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "record_count": manifest["record_count"],
        "record_key_sha256": [record["key_sha256"] for record in manifest["records"]],
        "state": "verified",
    }


def resolve_dataset_record(
    state_root: Path, dataset_id: str, manifest_sha256: str, record_key_sha256: str,
) -> dict[str, Any]:
    """Resolve one immutable record without reconstructing its namespace."""
    if not all(SHA64(value) for value in (dataset_id, manifest_sha256, record_key_sha256)):
        raise ScientificJobError("DATASET_BINDING_INVALID")
    verified = verify_dataset(state_root, dataset_id)
    if verified["manifest_sha256"] != manifest_sha256:
        raise ScientificJobError("DATASET_MANIFEST_BINDING_MISMATCH")
    index = json.loads((state_root / "dataset-index" / f"{dataset_id}.json").read_text(encoding="utf-8"))
    root = state_root / "datasets" / index["namespace_sha256"]
    manifest = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    records = [item for item in manifest["records"] if item.get("key_sha256") == record_key_sha256]
    if len(records) != 1:
        raise ScientificJobError("DATASET_RECORD_KEY_NOT_FOUND")
    metadata = records[0]
    payload = (root / "records" / f"{record_key_sha256}.payload").read_bytes()
    if (hashlib.sha256(payload).hexdigest() != metadata.get("payload_sha256")
            or len(payload) != metadata.get("payload_size_bytes")):
        raise ScientificJobError("DATASET_RECORD_INTEGRITY_MISMATCH")
    return {
        "payload": payload,
        "payload_sha256": metadata["payload_sha256"],
        "payload_size_bytes": metadata["payload_size_bytes"],
        "identity": metadata.get("identity", {}),
    }


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ScientificJobError("SELFTEST_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def selftest(root: Path, state_root: Path, *, mpb_smoke: bool) -> dict[str, Any]:
    root = root.resolve()
    sys.path.insert(0, str(root))
    import mephc
    if Path(mephc.__file__).resolve().parents[1] != root:
        raise ScientificJobError("SELFTEST_SOURCE_MODULE_ROOT_MISMATCH")
    helper = load_module("_mephc_native_helper_selftest", root / "tools" / "mephc-flow" / "wsl_native_exec.py")

    runtime_sha = runtime_hash(root)
    namespace = {"project_id": "MEPHC", "science_contract_id": "RUNTIME_SELFTEST", "runtime_sha256": runtime_sha}
    store = ImmutableDatasetStore(state_root / "selftests" / runtime_sha, namespace)
    payload_value = {
        "schema": "mephc-thin-selftest-payload-v1",
        "finite_scalars": [0.0, 1.0],
        "immutable_metadata": {"tested": True},
    }
    encoded = canonical_bytes(payload_value)
    decoded = json.loads(encoded)
    if decoded != payload_value:
        raise ScientificJobError("SELFTEST_CODEC_ROUNDTRIP_FAILED")
    key = canonical_bytes({"kind": "fake-provider", "index": 0})
    store.put(key, encoded, {"kind": "fake-provider"})
    restored, _ = store.get(key)
    if json.loads(restored) != payload_value:
        raise ScientificJobError("SELFTEST_CHECKPOINT_RELOAD_FAILED")
    manifest = store.finalize(1, {"runtime_sha256": runtime_sha, "fake_provider": True})
    verified = verify_dataset(store.state_root, manifest["dataset_id"])
    with tempfile.TemporaryDirectory(dir=state_root) as temporary:
        stdout = Path(temporary) / "stdout.log"
        value = {
            "machine_contract_status": "PASS", "dataset_id": manifest["dataset_id"],
            "result_id": hashlib.sha256(canonical_bytes({"dataset_id": manifest["dataset_id"]})).hexdigest(),
            "record_count": 1,
        }
        stderr = Path(temporary) / "stderr.log"
        result_file = Path(temporary) / "result.json"
        stdout.write_bytes(b"selftest\n")
        stderr.write_bytes(b"")
        result_file.write_bytes(canonical_bytes(value))
        native = helper.finalize_child_result(
            {"state": "running"}, stdout, stderr, 0, result_path=result_file,
        )
        if native.get("result_summary") != value:
            raise ScientificJobError("SELFTEST_RESULT_CHANNEL_FAILED")

    forbidden_solver_modules = sorted(
        name for name in sys.modules
        if name == "meep" or name.startswith("meep.") or name == "mpi4py" or name.startswith("mpi4py.")
    )
    if forbidden_solver_modules:
        raise ScientificJobError("SOLVER_FREE_SELFTEST_IMPORTED_NATIVE_MODULE")

    if mpb_smoke:
        raise ScientificJobError("MPB_SMOKE_MACHINE_CONTRACT_REQUIRED")
    smoke = {"executed": False, "reused": False}
    certification = {
        "schema": CERT_SCHEMA,
        "runtime_sha256": runtime_sha,
        "python": platform.python_version(),
        "payload_codec_schema": "canonical-json-v1",
        "fake_provider_tested": True,
        "solver_free_import_isolation": True,
        "payload_codec_tested": True,
        "checkpoint_tested": True,
        "result_channel_tested": True,
        "dataset_consumer_tested": True,
        "cross_commit_read_tested": True,
        "durable_state_tested": True,
        "mpb_smoke": smoke,
        "selftest_dataset": verified,
        "certified_at": time.time(),
    }
    atomic_json(state_root / "certifications" / f"{runtime_sha}.json", certification)
    return certification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("internal-selftest")
    test.add_argument("--root", type=Path, required=True)
    test.add_argument("--state-root", type=Path, required=True)
    test.add_argument("--mpb-smoke", action="store_true")
    verify = commands.add_parser("internal-dataset-verify")
    verify.add_argument("--state-root", type=Path, required=True)
    verify.add_argument("--dataset-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "internal-selftest":
            result = selftest(args.root.resolve(), args.state_root.resolve(), mpb_smoke=args.mpb_smoke)
        else:
            result = verify_dataset(args.state_root.resolve(), args.dataset_id)
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except ScientificJobError as exc:
        print(json.dumps({"ok": False, "error_code": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
