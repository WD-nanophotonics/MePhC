"""Private, fixed-scope science runtime for the direct MePhC flow.

This module is deliberately narrow: it exposes one R8 provider factory and
one exact-key retention context.  It is not a general runner, native command
launcher, provider builder, or filesystem API.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
from typing import Any, Callable


PROJECT_ID = "MEPHC"
SCIENCE_CONTRACT_ID = "E9F_QP_B_C2_C3_R8_LOCKED_SET"
FROZEN_GRAPH_RELATIVE = Path("audit/e9f/qp_b_c2_c3_r8_global_provider_request_graph.json")
ENTRYPOINT_RELATIVE = Path("audit/e9f/qp_b_c2_c3_r8_locked_set_native.py")
DIRECT_FLOW_STATE_ROOT = Path("/home/icy/.local/share/mephc-runtime/science")
MAX_UNIQUE_REQUESTS = 210
MAX_FRESH_SOLVER_EXECUTIONS = 210
RESOLUTION_VALUES = {"R96": 96, "R128": 128, "R160": 160}
H_REPRESENTATION = "mpb_periodic_h_l2_v1"


class ScienceRuntimeError(RuntimeError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    finally:
        temporary.unlink(missing_ok=True)


def _payload_has_state(payload: Any) -> bool:
    if isinstance(payload, dict):
        return "frequencies" in payload and "normalized_vectors" in payload
    return hasattr(payload, "frequencies") and hasattr(payload, "normalized_vectors")


class ExactKeyRetention:
    """Private exact-key store whose location is owned by direct-flow state."""

    def __init__(self, namespace: dict[str, Any]) -> None:
        self.namespace = dict(namespace)
        if self.namespace.get("project_id") != PROJECT_ID:
            raise ScienceRuntimeError("RETENTION_NAMESPACE_PROJECT_INVALID")
        self.root = DIRECT_FLOW_STATE_ROOT / PROJECT_ID / SCIENCE_CONTRACT_ID / self.namespace["source_commit"]
        self.records = self.root / "records"
        self.completed: set[str] = set()
        self._manifest = self.load_run_manifest()

    def _paths(self, key: bytes) -> tuple[Path, Path]:
        digest = hashlib.sha256(key).hexdigest()
        return self.records / f"{digest}.payload", self.records / f"{digest}.json"

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
            payload = pickle.loads(payload_path.read_bytes())
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError) as exc:
            raise ScienceRuntimeError("RETENTION_PAYLOAD_CORRUPT") from exc
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
        _atomic_bytes(payload_path, pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
        _atomic_bytes(metadata_path, json.dumps({
            "schema": "mephc_direct_flow_exact_key_record_v1",
            "key_sha256": key_sha,
            "identity": expected,
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

    def finalize_run_manifest(self) -> dict[str, Any]:
        value = {
            "schema": "mephc_direct_flow_r8_manifest_v1",
            "identity": self.namespace,
            "completed_key_sha256": sorted(self.completed),
            "completed_count": len(self.completed),
        }
        _atomic_bytes(self.root / "run-manifest.json", json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        self._manifest = value
        return value


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

    def execute(self, plan: list[dict[str, Any]]) -> tuple[dict[bytes, Any], int, int]:
        if len(plan) > MAX_UNIQUE_REQUESTS:
            raise ScienceRuntimeError("PROVIDER_REQUEST_CAP_EXCEEDED")
        results: dict[bytes, Any] = {}
        reused = 0
        fresh = 0
        for item in plan:
            key = _canonical_key(item["request_key"])
            payload = self.retention.lookup_exact(key)
            if payload is not None:
                results[key] = payload
                reused += 1
                continue
            if fresh >= MAX_FRESH_SOLVER_EXECUTIONS:
                raise ScienceRuntimeError("FRESH_SOLVER_EXECUTION_CAP_EXCEEDED")
            payload = self.provider_solve(item["request_key"])
            self.retention.store_exact(key, payload, self.retention.expected_identity(key))
            self.retention.mark_complete(key)
            results[key] = payload
            fresh += 1
        self.retention.finalize_run_manifest()
        return results, reused, fresh


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
