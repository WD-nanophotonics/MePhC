#!/home/icy/miniconda3/envs/mp/bin/python
"""Generic, local-only Scientific Native Job primitives for direct-flow."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import time
from typing import Any


CONTRACT_SCHEMA = "mephc-science-work-order-v1"
DATASET_SCHEMA = "mephc-scientific-dataset-v1"
RECORD_SCHEMA = "mephc-scientific-record-v1"
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


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _budget(raw: dict[str, Any], *names: str) -> tuple[int, bool]:
    value = next((raw[name] for name in names if name in raw), 0)
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < 0:
        return 0, True
    return value, False


def _entrypoint(value: Any) -> str | None:
    if isinstance(value, dict):
        if value.get("type") == "null" and value.get("value") is None:
            return None
        value = value.get("value") or value.get("path")
    if not isinstance(value, str):
        return None
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".py":
        return None
    return str(candidate)


def normalize_contract(value: Any) -> Any:
    """Reduce Chat dialects to one minimum-risk execution intent."""
    if not isinstance(value, dict):
        return value
    raw = json.loads(json.dumps(value))
    warnings: list[str] = []
    work_order_id = raw.get("work_order_id", raw.get("WORK_ORDER_ID"))
    source_commit = raw.get("source_commit", raw.get("source_sha", raw.get("SOURCE_SHA")))
    inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
    raw_budgets = raw.get("budgets") if isinstance(raw.get("budgets"), dict) else {}
    native, bad_native = _budget(raw_budgets, "native_invocations")
    providers, bad_provider = _budget(raw_budgets, "provider_requests", "provider_executions")
    solvers, bad_solver = _budget(raw_budgets, "solver_executions")
    if bad_native or bad_provider or bad_solver:
        warnings.append("invalid_budget_reduced_to_zero")
    if native > 1:
        native = 1
        warnings.append("native_budget_clamped_to_one")
    entrypoint = _entrypoint(raw.get("entrypoint"))
    if raw.get("entrypoint") is not None and entrypoint is None:
        warnings.append("invalid_entrypoint_ignored")
    if native and entrypoint is None:
        native = providers = solvers = 0
        warnings.append("native_disabled_without_safe_entrypoint")
    if not native and (providers or solvers):
        providers = solvers = 0
        warnings.append("orphan_execution_budgets_reduced_to_zero")
    raw_action = str(raw.get("action", "")).casefold()
    raw_kind = str(raw.get("kind", "")).casefold()
    if native:
        action = "acquire"
    elif raw_kind == "infrastructure":
        action = "infrastructure"
        if entrypoint:
            entrypoint = None
            warnings.append("infrastructure_entrypoint_ignored")
    elif entrypoint:
        action = "analyze"
    elif raw_action == "corrective" or str(raw.get("mode", "")).casefold() == "corrective":
        action = "corrective"
    else:
        action = "infrastructure"
    budgets = {
        "native_invocations": native,
        "provider_requests": providers if native else 0,
        "solver_executions": solvers if native else 0,
    }
    output = raw.get("expected_output") if isinstance(raw.get("expected_output"), dict) else {}
    dataset_schema = output.get("dataset_schema") if isinstance(output.get("dataset_schema"), str) else None
    result_schema = output.get("result_schema") if isinstance(output.get("result_schema"), str) else None
    if action in {"acquire", "analyze"} and not result_schema:
        result_schema = "mephc-result-" + digest({"work_order_id": work_order_id, "entrypoint": entrypoint})[:16] + "-v1"
        warnings.append("result_schema_derived")
    capabilities = ["exact_checkout", "sandbox_publication", "result_channel", "automatic_provenance"]
    if native:
        capabilities.append("native_execution")
        if solvers:
            capabilities.append("mpb")
    if "datasets" in inputs:
        capabilities.extend(["private_retention", "cross_commit_dataset_read"])
    allowed = _strings(raw.get("allowed_writes"))
    if action != "infrastructure" and any(path.startswith("tools/mephc-flow/") for path in allowed):
        warnings.append("framework_write_outside_advisory_scope")
    result = {
        "schema": CONTRACT_SCHEMA,
        "kind": "SCIENCE" if action != "infrastructure" else "INFRASTRUCTURE",
        "work_order_id": work_order_id,
        "source_commit": source_commit,
        "action": action,
        "project": ".",
        "entrypoint": entrypoint,
        "inputs": inputs,
        "budgets": budgets,
        "required_capabilities": capabilities,
        "allowed_writes": allowed,
        "expected_output": {"dataset_schema": dataset_schema, "result_schema": result_schema},
        "acceptance_criteria": _strings(raw.get("acceptance_criteria")),
        "forbidden": _strings(raw.get("forbidden")),
        "mode": "CORRECTIVE" if action == "corrective" else "STANDARD",
        "original_work_order_class": str(raw.get("kind", "UNSPECIFIED")),
        "contract_warnings": sorted(set(warnings)),
        "raw_contract_sha256": digest(raw),
    }
    if isinstance(raw.get("parent_work_order_id"), str):
        result["parent_work_order_id"] = raw["parent_work_order_id"]
    return result


def validate_contract(value: Any) -> dict[str, Any]:
    result = normalize_contract(value)
    if not isinstance(result, dict):
        raise ScientificJobError("WORK_ORDER_MACHINE_CONTRACT_REQUIRED")
    if not isinstance(result.get("work_order_id"), str) or not result["work_order_id"].startswith("MEPHC-"):
        raise ScientificJobError("WORK_ORDER_CONTRACT_ID_INVALID")
    if not SHA40(result.get("source_commit")):
        raise ScientificJobError("WORK_ORDER_CONTRACT_SOURCE_INVALID")
    result["contract_sha256"] = digest({
        key: result[key] for key in (
            "work_order_id", "source_commit", "action", "entrypoint", "inputs", "budgets",
            "expected_output",
        )
    })
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
