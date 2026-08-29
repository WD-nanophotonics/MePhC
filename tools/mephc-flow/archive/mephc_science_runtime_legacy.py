"""Private, fixed-scope science runtime for the direct MePhC flow.

This module is deliberately narrow: it exposes one R8 provider factory and
one exact-key retention context.  It is not a general runner, native command
launcher, provider builder, or filesystem API.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import importlib.util
from typing import Any, Callable


PROJECT_ID = "MEPHC"
SCIENCE_CONTRACT_ID = "E9F_QP_B_C2_C3_R8_LOCKED_SET"
FROZEN_GRAPH_RELATIVE = Path("audit/e9f/qp_b_c2_c3_r8_global_provider_request_graph.json")
ENTRYPOINT_RELATIVE = Path("audit/e9f/qp_b_c2_c3_r8_locked_set_native.py")
MAX_UNIQUE_REQUESTS = 210
MAX_FRESH_SOLVER_EXECUTIONS = 210
RESOLUTION_VALUES = {"R96": 96, "R128": 128, "R160": 160}
H_REPRESENTATION = "mpb_periodic_h_l2_v1"
RETENTION_PAYLOAD_CODEC_SCHEMA = "mephc_direct_flow_mpb_h_snapshot_payload_v1"


class ScienceRuntimeError(RuntimeError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _trusted_science_state_root() -> Path:
    """Derive private science state from the canonical runtime state module."""
    module_name = "_mephc_direct_flow_runtime_state"
    import sys
    if module_name not in sys.modules:
        path = _root() / "tools" / "mephc-flow" / "mephc_runtime.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ScienceRuntimeError("DIRECT_FLOW_RUNTIME_STATE_UNAVAILABLE")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    state = getattr(sys.modules[module_name], "SCIENCE_STATE", None)
    if not isinstance(state, Path):
        raise ScienceRuntimeError("DIRECT_FLOW_SCIENCE_STATE_UNAVAILABLE")
    return state


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False, capture_output=True, text=True, encoding="utf-8",
    )
    commit = result.stdout.strip()
    if result.returncode or len(commit) != 40:
        raise ScienceRuntimeError("DIRECT_FLOW_SOURCE_COMMIT_UNAVAILABLE")
    return commit


def _identity() -> dict[str, Any]:
    root = _root()
    graph = root / FROZEN_GRAPH_RELATIVE
    entrypoint = root / ENTRYPOINT_RELATIVE
    if not graph.is_file() or not entrypoint.is_file():
        raise ScienceRuntimeError("R8_RUNTIME_ARTIFACTS_UNAVAILABLE")
    return {
        "project_id": PROJECT_ID,
        "science_contract_id": SCIENCE_CONTRACT_ID,
        "source_commit": _source_commit(root),
        "entrypoint_sha256": _sha256(entrypoint),
        "graph_sha256": _sha256(graph),
    }


def _key_fields(key: bytes) -> dict[str, Any]:
    try:
        value = json.loads(key.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScienceRuntimeError("CANONICAL_PROVIDER_KEY_INVALID") from exc
    if not isinstance(value, dict) or set(value) != {
        "fr", "resolution", "canonical_k_coordinate_units_1_over_144",
        "source_model_identity", "provider_configuration_identity",
        "band_request_configuration",
    }:
        raise ScienceRuntimeError("CANONICAL_PROVIDER_KEY_INVALID")
    return value


def _request_identity(namespace: dict[str, Any], key: bytes) -> dict[str, Any]:
    value = _key_fields(key)
    if value["fr"] != 0 or value["resolution"] not in RESOLUTION_VALUES:
        raise ScienceRuntimeError("R8_REQUEST_SCOPE_INVALID")
    return {
        **namespace,
        "resolution": value["resolution"],
        "canonical_k_coordinate_units_1_over_144": value[
            "canonical_k_coordinate_units_1_over_144"
        ],
        "source_model_identity": value["source_model_identity"],
        "provider_configuration_identity": value["provider_configuration_identity"],
        "band_request_configuration": value["band_request_configuration"],
    }


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Durably publish a replacement in the canonical Linux runtime."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ScienceRuntimeError("RETENTION_DIRECTORY_FSYNC_FAILED") from exc


def _payload_has_state(payload: Any) -> bool:
    if isinstance(payload, dict):
        return "frequencies" in payload and "normalized_vectors" in payload
    return hasattr(payload, "frequencies") and hasattr(payload, "normalized_vectors")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "items") and not isinstance(value, (str, bytes, bytearray)):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ScienceRuntimeError("RETENTION_METADATA_NOT_JSON_SAFE")


def encode_snapshot(payload: Any) -> bytes:
    """Encode MPBHEnvelopeSnapshot using numeric NPZ arrays and JSON metadata."""
    import numpy as np
    from mephc.mpb_spectral import MPBHEnvelopeSnapshot
    if not isinstance(payload, MPBHEnvelopeSnapshot):
        if isinstance(payload, dict) and "frequencies" in payload and "normalized_vectors" in payload:
            metadata = _canonical_json_bytes({
                "schema": RETENTION_PAYLOAD_CODEC_SCHEMA,
                "kind": "explicit_test_equivalent",
                "payload": _jsonable(payload),
            })
            buffer = io.BytesIO()
            np.savez_compressed(buffer, metadata=np.frombuffer(metadata, dtype=np.uint8))
            return buffer.getvalue()
        raise ScienceRuntimeError("RETENTION_PAYLOAD_TYPE_UNSUPPORTED")
    if payload.provenance.get("representation") != H_REPRESENTATION:
        raise ScienceRuntimeError("RETENTION_PAYLOAD_REPRESENTATION_INVALID")
    arrays = {
        "h_fields": np.asarray(payload.h_fields),
        "frequencies": np.asarray(payload.frequencies),
        "raw_norms": np.asarray(payload.raw_norms),
        "gram_matrix": np.asarray(payload.gram_matrix),
    }
    if payload.e_fields is not None:
        arrays["e_fields"] = np.asarray(payload.e_fields)
    if any(array.dtype.kind == "O" or not np.all(np.isfinite(array)) for array in arrays.values()):
        raise ScienceRuntimeError("RETENTION_PAYLOAD_ARRAY_INVALID")
    if arrays["h_fields"].ndim != 4 or arrays["h_fields"].shape[-1] != 3:
        raise ScienceRuntimeError("RETENTION_PAYLOAD_H_SHAPE_INVALID")
    if arrays["raw_norms"].ndim != 1 or np.any(arrays["raw_norms"] <= 0):
        raise ScienceRuntimeError("RETENTION_PAYLOAD_NORMS_INVALID")
    states = []
    for state in payload.raw_eigenstates:
        states.append({
            "k_point": list(state.k_point),
            "solver_index": state.solver_index,
            "eigenvalue": state.eigenvalue,
            "metadata": _jsonable(state.metadata),
        })
    metadata = _canonical_json_bytes({
        "schema": RETENTION_PAYLOAD_CODEC_SCHEMA,
        "kind": "mpb_h_snapshot",
        "k_point": list(payload.k_point),
        "max_normalization_error": payload.max_normalization_error,
        "max_off_diagonal_gram": payload.max_off_diagonal_gram,
        "orthogonality_status": payload.orthogonality_status,
        "normalization_tolerance": payload.normalization_tolerance,
        "orthogonality_tolerance": payload.orthogonality_tolerance,
        "provenance": _jsonable(payload.provenance),
        "raw_eigenstates": states,
        "e_fields_present": payload.e_fields is not None,
    })
    buffer = io.BytesIO()
    np.savez_compressed(buffer, metadata=np.frombuffer(metadata, dtype=np.uint8), **arrays)
    return buffer.getvalue()


def decode_snapshot(payload_bytes: bytes) -> Any:
    """Decode and validate only the fixed numeric/JSON snapshot schema."""
    import numpy as np
    from mephc.eigenspace import RawEigenstate
    from mephc.mpb_spectral import MPBHEnvelopeSnapshot
    try:
        with np.load(io.BytesIO(payload_bytes), allow_pickle=False) as archive:
            if "metadata" not in archive.files:
                raise ScienceRuntimeError("RETENTION_CODEC_METADATA_MISSING")
            metadata = json.loads(archive["metadata"].tobytes().decode("utf-8"))
            if metadata.get("schema") != RETENTION_PAYLOAD_CODEC_SCHEMA:
                raise ScienceRuntimeError("RETENTION_CODEC_SCHEMA_INVALID")
            if metadata.get("kind") == "explicit_test_equivalent":
                if set(archive.files) != {"metadata"}:
                    raise ScienceRuntimeError("RETENTION_CODEC_FIELDS_INVALID")
                return metadata["payload"]
            expected = {"metadata", "h_fields", "frequencies", "raw_norms", "gram_matrix"}
            if metadata.get("kind") != "mpb_h_snapshot":
                raise ScienceRuntimeError("RETENTION_CODEC_KIND_INVALID")
            if metadata.get("e_fields_present"):
                expected.add("e_fields")
            if set(archive.files) != expected:
                raise ScienceRuntimeError("RETENTION_CODEC_FIELDS_INVALID")
            arrays = {name: np.asarray(archive[name]) for name in expected if name != "metadata"}
            if any(array.dtype.kind == "O" or not np.all(np.isfinite(array)) for array in arrays.values()):
                raise ScienceRuntimeError("RETENTION_CODEC_ARRAY_INVALID")
            h_fields = arrays["h_fields"]
            frequencies = arrays["frequencies"]
            raw_norms = arrays["raw_norms"]
            gram = arrays["gram_matrix"]
            if (h_fields.ndim != 4 or h_fields.shape[-1] != 3
                    or frequencies.ndim != 1 or raw_norms.ndim != 1
                    or gram.ndim != 2 or h_fields.shape[0] != frequencies.size
                    or raw_norms.size != frequencies.size or gram.shape != (frequencies.size, frequencies.size)
                    or np.any(raw_norms <= 0)):
                raise ScienceRuntimeError("RETENTION_CODEC_SHAPE_INVALID")
            if metadata.get("e_fields_present") and arrays["e_fields"].shape != h_fields.shape:
                raise ScienceRuntimeError("RETENTION_CODEC_E_SHAPE_INVALID")
            normalized = tuple(np.asarray(h_fields[index].reshape(-1), dtype=np.complex128) / raw_norms[index] for index in range(h_fields.shape[0]))
            states = tuple(
                RawEigenstate(
                    tuple(item["k_point"]), int(item["solver_index"]), float(item["eigenvalue"]), normalized[index], item["metadata"]
                )
                for index, item in enumerate(metadata.get("raw_eigenstates", []))
            )
            if len(states) != frequencies.size:
                raise ScienceRuntimeError("RETENTION_CODEC_STATE_COUNT_INVALID")
            return MPBHEnvelopeSnapshot(
                k_point=tuple(metadata["k_point"]), frequencies=frequencies,
                h_fields=h_fields, raw_norms=raw_norms, normalized_vectors=normalized,
                gram_matrix=gram, max_normalization_error=float(metadata["max_normalization_error"]),
                max_off_diagonal_gram=float(metadata["max_off_diagonal_gram"]),
                orthogonality_status=metadata["orthogonality_status"],
                normalization_tolerance=float(metadata["normalization_tolerance"]),
                orthogonality_tolerance=float(metadata["orthogonality_tolerance"]),
                raw_eigenstates=states, provenance=metadata["provenance"],
                e_fields=arrays.get("e_fields"),
            )
    except ScienceRuntimeError:
        raise
    except Exception as exc:
        raise ScienceRuntimeError("RETENTION_CODEC_DECODE_FAILED") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _dataset_id(content: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(content)).hexdigest()


def _manifest_sha(content: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in content.items() if key != "manifest_sha256"}
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


class ExactKeyRetention:
    """Private exact-key store whose location is owned by direct-flow state."""

    def __init__(self, namespace: dict[str, Any]) -> None:
        self.namespace = dict(namespace)
        if self.namespace.get("project_id") != PROJECT_ID:
            raise ScienceRuntimeError("RETENTION_NAMESPACE_PROJECT_INVALID")
        self.root = _trusted_science_state_root() / PROJECT_ID / SCIENCE_CONTRACT_ID / self.namespace["source_commit"]
        self.records = self.root / "records"
        self.completed: set[str] = set()
        self._manifest = self.load_run_manifest()

    def _paths(self, key: bytes) -> tuple[Path, Path]:
        digest = hashlib.sha256(key).hexdigest()
        return self.records / f"{digest}.payload", self.records / f"{digest}.json"

    @property
    def namespace_id(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.namespace)).hexdigest()[:24]

    def expected_identity(self, key: bytes) -> dict[str, Any]:
        return _request_identity(self.namespace, key)

    def lookup_exact(self, key: bytes) -> Any | None:
        payload_path, metadata_path = self._paths(key)
        if not metadata_path.is_file() or not payload_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScienceRuntimeError("RETENTION_METADATA_CORRUPT") from exc
        if (metadata.get("complete") is not True
                or metadata.get("key_sha256") != hashlib.sha256(key).hexdigest()
                or metadata.get("identity") != self.expected_identity(key)):
            return None
        try:
            payload_bytes = payload_path.read_bytes()
        except OSError as exc:
            raise ScienceRuntimeError("RETENTION_PAYLOAD_UNAVAILABLE") from exc
        if (metadata.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest()
                or metadata.get("payload_size_bytes") != len(payload_bytes)):
            raise ScienceRuntimeError("RETENTION_PAYLOAD_INTEGRITY_MISMATCH")
        payload = decode_snapshot(payload_bytes)
        if not _payload_has_state(payload):
            raise ScienceRuntimeError("RETENTION_PAYLOAD_STATE_INCOMPLETE")
        self.completed.add(metadata["key_sha256"])
        return payload

    def store_exact(self, key: bytes, payload: Any, identity_metadata: dict[str, Any]) -> None:
        expected = self.expected_identity(key)
        if identity_metadata != expected:
            raise ScienceRuntimeError("RETENTION_IDENTITY_MISMATCH")
        if not _payload_has_state(payload):
            raise ScienceRuntimeError("RETENTION_PAYLOAD_STATE_INCOMPLETE")
        payload_path, metadata_path = self._paths(key)
        key_sha = hashlib.sha256(key).hexdigest()
        payload_bytes = encode_snapshot(payload)
        payload_sha = hashlib.sha256(payload_bytes).hexdigest()
        _atomic_bytes(payload_path, payload_bytes)
        _atomic_bytes(metadata_path, json.dumps({
            "schema": "mephc_direct_flow_exact_key_record_v1",
            "key_sha256": key_sha,
            "identity": expected,
            "payload_sha256": payload_sha,
            "payload_size_bytes": len(payload_bytes),
            "complete": False,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def mark_complete(self, key: bytes) -> None:
        _, metadata_path = self._paths(key)
        if not metadata_path.is_file() or not self._paths(key)[0].is_file():
            raise ScienceRuntimeError("RETENTION_COMPLETE_WITHOUT_PAYLOAD")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("identity") != self.expected_identity(key):
            raise ScienceRuntimeError("RETENTION_IDENTITY_MISMATCH")
        metadata["complete"] = True
        _atomic_bytes(metadata_path, json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        self.completed.add(hashlib.sha256(key).hexdigest())

    def record_metadata(self, key: bytes) -> dict[str, Any]:
        payload_path, metadata_path = self._paths(key)
        if not payload_path.is_file() or not metadata_path.is_file():
            raise ScienceRuntimeError("RETENTION_RECORD_INCOMPLETE")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScienceRuntimeError("RETENTION_METADATA_CORRUPT") from exc
        if (metadata.get("complete") is not True
                or metadata.get("identity") != self.expected_identity(key)
                or metadata.get("key_sha256") != hashlib.sha256(key).hexdigest()):
            raise ScienceRuntimeError("RETENTION_RECORD_IDENTITY_INVALID")
        payload_bytes = payload_path.read_bytes()
        if (metadata.get("payload_sha256") != hashlib.sha256(payload_bytes).hexdigest()
                or metadata.get("payload_size_bytes") != len(payload_bytes)):
            raise ScienceRuntimeError("RETENTION_PAYLOAD_INTEGRITY_MISMATCH")
        return {
            "key_sha256": metadata["key_sha256"],
            "payload_sha256": metadata["payload_sha256"],
            "payload_size_bytes": metadata["payload_size_bytes"],
            "identity": metadata["identity"],
        }

    def finalize_dataset_manifest(
        self, plan: list[dict[str, Any]], *, fresh_provider_execution_count: int,
        cache_reuse_count: int, fresh_mpb_execution_observed: bool,
    ) -> dict[str, Any]:
        if len(plan) != MAX_UNIQUE_REQUESTS:
            raise ScienceRuntimeError("DATASET_COMPLETION_COUNT_INVALID")
        module = _entrypoint_module()
        records = [self.record_metadata(module.canonical_key(item["request_key"])) for item in plan]
        records.sort(key=lambda item: item["key_sha256"])
        keys = [_key_fields(module.canonical_key(item["request_key"])) for item in plan]
        identities = {
            field: {value[field] for value in keys}
            for field in ("source_model_identity", "provider_configuration_identity", "band_request_configuration")
        }
        if any(len(values) != 1 for values in identities.values()):
            raise ScienceRuntimeError("DATASET_IDENTITY_SET_INVALID")
        content: dict[str, Any] = {
            "schema": "mephc_direct_flow_r8_acquisition_dataset_v1",
            "project_id": PROJECT_ID,
            "science_contract_id": SCIENCE_CONTRACT_ID,
            "acquisition_source_commit": self.namespace["source_commit"],
            "entrypoint_sha256": self.namespace["entrypoint_sha256"],
            "graph_sha256": self.namespace["graph_sha256"],
            "source_model_identity": next(iter(identities["source_model_identity"])),
            "provider_configuration_identity": next(iter(identities["provider_configuration_identity"])),
            "band_request_configuration": next(iter(identities["band_request_configuration"])),
            "logical_provider_demand_count": 216,
            "unique_provider_request_count": MAX_UNIQUE_REQUESTS,
            "completed_key_count": MAX_UNIQUE_REQUESTS,
            "records": records,
            "fresh_provider_execution_count": fresh_provider_execution_count,
            "cache_reuse_count": cache_reuse_count,
            "fresh_mpb_execution_observed": bool(fresh_mpb_execution_observed),
            "dataset_is_mpb_backed": True,
            "completion_state": "COMPLETE",
        }
        content["dataset_id"] = _dataset_id(content)
        content["manifest_sha256"] = _manifest_sha(content)
        manifest_path = self.root / "acquisition-dataset-manifest.json"
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ScienceRuntimeError("DATASET_MANIFEST_CORRUPT") from exc
            static_fields = set(content) - {
                "fresh_provider_execution_count", "cache_reuse_count",
                "fresh_mpb_execution_observed", "dataset_id", "manifest_sha256",
            }
            if any(existing.get(field) != content[field] for field in static_fields):
                raise ScienceRuntimeError("DATASET_MANIFEST_IMMUTABILITY_VIOLATION")
            return existing
        else:
            _atomic_bytes(manifest_path, _canonical_json_bytes(content))
        return content

    def load_run_manifest(self) -> dict[str, Any]:
        path = self.root / "run-manifest.json"
        if not path.is_file():
            return {"schema": "mephc_direct_flow_r8_manifest_v1", "identity": self.namespace, "completed_key_sha256": []}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScienceRuntimeError("RETENTION_RUN_MANIFEST_CORRUPT") from exc
        if value.get("identity") != self.namespace:
            raise ScienceRuntimeError("RETENTION_RUN_MANIFEST_IDENTITY_MISMATCH")
        self.completed.update(value.get("completed_key_sha256", []))
        return value

    def finalize_run_manifest(self, summary: dict[str, Any] | None = None) -> dict[str, Any]:
        value = {
            "schema": "mephc_direct_flow_r8_manifest_v1",
            "identity": self.namespace,
            "completed_key_sha256": sorted(self.completed),
            "completed_count": len(self.completed),
        }
        if summary:
            value.update(summary)
        _atomic_bytes(self.root / "run-manifest.json", json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        self._manifest = value
        return value


class ImmutableR8DatasetConsumer:
    """Read-only consumer for a completed acquisition from any later commit."""

    REQUIRED_BINDING_FIELDS = frozenset({
        "acquisition_source_commit", "acquisition_dataset_id",
        "dataset_manifest_sha256", "entrypoint_sha256", "graph_sha256",
    })

    def __init__(self, binding: dict[str, str]) -> None:
        if set(binding) != set(self.REQUIRED_BINDING_FIELDS):
            raise ScienceRuntimeError("DATASET_BINDING_FIELDS_INVALID")
        if (len(binding["acquisition_source_commit"]) != 40
                or any(len(binding[field]) != 64 for field in (
                    "acquisition_dataset_id", "dataset_manifest_sha256",
                    "entrypoint_sha256", "graph_sha256"))):
            raise ScienceRuntimeError("DATASET_BINDING_DIGEST_INVALID")
        namespace = {
            "project_id": PROJECT_ID,
            "science_contract_id": SCIENCE_CONTRACT_ID,
            "source_commit": binding["acquisition_source_commit"],
            "entrypoint_sha256": binding["entrypoint_sha256"],
            "graph_sha256": binding["graph_sha256"],
        }
        retention = ExactKeyRetention(namespace)
        manifest_path = retention.root / "acquisition-dataset-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScienceRuntimeError("DATASET_MANIFEST_UNAVAILABLE") from exc
        if manifest.get("manifest_sha256") != binding["dataset_manifest_sha256"]:
            raise ScienceRuntimeError("DATASET_MANIFEST_SHA_MISMATCH")
        if _manifest_sha(manifest) != binding["dataset_manifest_sha256"]:
            raise ScienceRuntimeError("DATASET_MANIFEST_INTEGRITY_MISMATCH")
        unsigned = {key: value for key, value in manifest.items() if key not in {"dataset_id", "manifest_sha256"}}
        if manifest.get("dataset_id") != binding["acquisition_dataset_id"] or _dataset_id(unsigned) != binding["acquisition_dataset_id"]:
            raise ScienceRuntimeError("DATASET_ID_MISMATCH")
        if (manifest.get("project_id") != PROJECT_ID
                or manifest.get("science_contract_id") != SCIENCE_CONTRACT_ID
                or manifest.get("acquisition_source_commit") != binding["acquisition_source_commit"]
                or manifest.get("entrypoint_sha256") != binding["entrypoint_sha256"]
                or manifest.get("graph_sha256") != binding["graph_sha256"]
                or manifest.get("completion_state") != "COMPLETE"
                or manifest.get("completed_key_count") != MAX_UNIQUE_REQUESTS):
            raise ScienceRuntimeError("DATASET_MANIFEST_IDENTITY_INVALID")
        self.binding = dict(binding)
        self.retention = retention
        self.manifest = manifest
        self.records = {record["key_sha256"]: record for record in manifest.get("records", [])}
        if len(self.records) != MAX_UNIQUE_REQUESTS:
            raise ScienceRuntimeError("DATASET_RECORD_COUNT_INVALID")

    def lookup_exact(self, key: bytes) -> Any:
        key_sha = hashlib.sha256(key).hexdigest()
        record = self.records.get(key_sha)
        if record is None:
            raise ScienceRuntimeError("DATASET_KEY_NOT_IN_IMMUTABLE_DATASET")
        payload = self.retention.lookup_exact(key)
        if payload is None:
            raise ScienceRuntimeError("DATASET_RECORD_NOT_COMPLETE")
        actual = self.retention.record_metadata(key)
        if {field: actual[field] for field in ("key_sha256", "payload_sha256", "payload_size_bytes")} != {
            field: record[field] for field in ("key_sha256", "payload_sha256", "payload_size_bytes")
        }:
            raise ScienceRuntimeError("DATASET_RECORD_METADATA_MISMATCH")
        return payload


def open_r8_dataset(binding: dict[str, str]) -> ImmutableR8DatasetConsumer:
    """Open only the fixed, immutable, read-only R8 dataset binding."""
    return ImmutableR8DatasetConsumer(binding)


def _verified_plan() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    module = _entrypoint_module()
    graph = module.load_frozen_graph()
    module.verify_graph(graph)
    return module, module.build_provider_plan(graph)


def _build_live_provider(resolution: str) -> Any:
    """Build the accepted E9 geometry plus the existing H-only MPB provider."""
    try:
        import meep as mp
        from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs
        from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
    except ImportError as exc:
        raise ScienceRuntimeError("EXISTING_E9_MPB_PROVIDER_UNAVAILABLE") from exc
    geometry = geometry_inputs()
    _, lattice, solver_geometry, background = build_inputs(geometry)
    return MPBLiveSpectralProvider(
        geometry=list(solver_geometry), geometry_lattice=lattice,
        resolution=RESOLUTION_VALUES[resolution], num_bands=6,
        polarization=mp.TE, default_material=background,
        eigensolver_tolerance=1e-7, deterministic=True, mesh_size=3,
    )


def build_r8_provider_factory() -> Callable[[dict[str, Any]], Any]:
    module, plan = _verified_plan()
    allowed = {module.canonical_key(item["request_key"]): item["request_key"] for item in plan}
    providers: dict[str, Any] = {}

    def provider_solve(request_key: dict[str, Any]) -> Any:
        key = module.canonical_key(request_key)
        if key not in allowed:
            raise ScienceRuntimeError("PROVIDER_REQUEST_OUTSIDE_FROZEN_GRAPH")
        resolution = request_key["resolution"]
        if resolution not in providers:
            providers[resolution] = _build_live_provider(resolution)
        provider = providers[resolution]
        coordinate = request_key["canonical_k_coordinate_units_1_over_144"]
        return provider.solve((coordinate["i"] / 144.0, coordinate["j"] / 144.0))

    return provider_solve


def _official_r8_provider_factory() -> Callable[[dict[str, Any]], Any]:
    return build_r8_provider_factory()


def _official_private_retention() -> ExactKeyRetention:
    return ExactKeyRetention(_identity())


class R8ScienceRuntime:
    def __init__(self, provider_solve: Callable[[dict[str, Any]], Any], retention: ExactKeyRetention) -> None:
        self.provider_solve = provider_solve
        self.retention = retention

    def execute(self, plan: list[dict[str, Any]]) -> dict[str, Any]:
        if len(plan) > MAX_UNIQUE_REQUESTS:
            raise ScienceRuntimeError("PROVIDER_REQUEST_CAP_EXCEEDED")
        reused = 0
        fresh = 0
        fresh_mpb_execution_observed = False
        for item in plan:
            key = _canonical_key(item["request_key"])
            payload = self.retention.lookup_exact(key)
            if payload is not None:
                reused += 1
                del payload
                continue
            if fresh >= MAX_FRESH_SOLVER_EXECUTIONS:
                raise ScienceRuntimeError("FRESH_SOLVER_EXECUTION_CAP_EXCEEDED")
            payload = self.provider_solve(item["request_key"])
            fresh_mpb_execution_observed = True
            self.retention.store_exact(key, payload, self.retention.expected_identity(key))
            self.retention.mark_complete(key)
            fresh += 1
            del payload
        namespace_id = hashlib.sha256(
            json.dumps(self.retention.namespace, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        dataset = self.retention.finalize_dataset_manifest(
            plan,
            fresh_provider_execution_count=fresh,
            cache_reuse_count=reused,
            fresh_mpb_execution_observed=fresh_mpb_execution_observed,
        )
        summary = {
            "science_contract_id": self.retention.namespace["science_contract_id"],
            "source_commit": self.retention.namespace["source_commit"],
            "acquisition_source_commit": dataset["acquisition_source_commit"],
            "entrypoint_sha256": self.retention.namespace["entrypoint_sha256"],
            "graph_sha256": self.retention.namespace["graph_sha256"],
            "logical_provider_demand_count": 216,
            "provider_request_count": len(plan),
            "cache_reuse_count": reused,
            "fresh_native_solver_execution_count": fresh,
            "completed_key_count": len(plan),
            "fresh_provider_execution_count": fresh,
            "fresh_mpb_execution_observed": fresh_mpb_execution_observed,
            "mpb_execution_observed": fresh_mpb_execution_observed,
            "dataset_is_mpb_backed": dataset["dataset_is_mpb_backed"],
            "acquisition_dataset_id": dataset["dataset_id"],
            "acquisition_dataset_manifest_sha256": dataset["manifest_sha256"],
            "failed_key_count": 0,
            "provider_failure_count": 0,
            "opaque_retention_namespace_id": namespace_id,
        }
        self.retention.finalize_run_manifest(summary)
        return summary


def _canonical_key(request_key: dict[str, Any]) -> bytes:
    return _entrypoint_module().canonical_key(request_key)


def _entrypoint_module():
    from importlib.util import module_from_spec, spec_from_file_location
    import sys
    module_name = "_mephc_r8_entrypoint_for_runtime"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = _root() / ENTRYPOINT_RELATIVE
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ScienceRuntimeError("R8_ENTRYPOINT_IMPORT_UNAVAILABLE")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def create_r8_runtime() -> R8ScienceRuntime:
    """Construct the sole official zero-argument R8 runtime context."""
    return R8ScienceRuntime(_official_r8_provider_factory(), _official_private_retention())


__all__ = [
    "ExactKeyRetention", "R8ScienceRuntime", "ScienceRuntimeError",
    "build_r8_provider_factory", "create_r8_runtime",
]
