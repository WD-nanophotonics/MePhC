"""Reusable audit campaign runtime with fail-closed identity and resume semantics.

This module is intentionally standard-library-only. It does not import MPB,
MPI, production scientific observables, or a project-specific live runner.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
try:
    import resource
except ImportError:
    resource = None
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence


class CampaignRuntimeError(RuntimeError):
    pass


class CampaignPreflightError(CampaignRuntimeError):
    pass


class ArtifactValidationError(CampaignRuntimeError):
    pass


class CheckpointValidationError(CampaignRuntimeError):
    pass


class ProcessReviewSchemaError(CampaignRuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _canonical_semantic_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not (value == value and abs(value) != float("inf")):
            raise ValueError("non-finite semantic coordinate")
        value = str(value)
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            return value
        normalized = format(number.normalize(), "f")
        return "0" if normalized in {"-0", ""} else normalized
    if isinstance(value, Mapping):
        return {str(key): _canonical_semantic_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_semantic_value(item) for item in value]
    return str(value)


def _authoritative_coordinate(row: Mapping[str, Any]) -> tuple[str, Any] | None:
    for key in ("authoritative_coordinate", "public_q", "coordinate", "q"):
        if key in row:
            return key, _canonical_semantic_value(row[key])
    return None


def _worker_coordinate(row: Mapping[str, Any]) -> tuple[str, Any] | None:
    for key in ("worker_coordinate", "actual_worker_coordinate", "worker_public_q"):
        if key in row:
            return key, _canonical_semantic_value(row[key])
    return None


def semantic_plan_fingerprint(rows: Sequence[Mapping[str, Any]], *, estimator_id: str, semantic_domain_id: str, spacing_id: str) -> str:
    payload = {
        "schema": "trilatt_semantic_plan_fingerprint_v2",
        "estimator_id": estimator_id,
        "semantic_domain_id": semantic_domain_id,
        "spacing_id": spacing_id,
        "rows": [
            {
                "sample_id": row["sample_id"],
                "sample_index": row.get("sample_index"),
                "grid_index": list(row.get("grid_index", [])),
                "fragment_index": row.get("fragment_index"),
                "triangle_index": row.get("triangle_index"),
                "topology_id": row.get("topology_id"),
                "authoritative_coordinate": _authoritative_coordinate(row),
            }
            for row in sorted(rows, key=lambda item: str(item["sample_id"]))
        ],
    }
    return sha256_bytes(canonical_json(payload))


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def current_rss_kib() -> int | None:
    try:
        if resource is None:
            return None
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, OSError, ValueError):
        return None


@dataclass(frozen=True)
class CampaignIdentity:
    execution_git_sha: str
    runner_sha256: str
    scientific_contract_sha256: str
    plan_semantic_id: str
    expected_sample_ids: tuple[str, ...]
    raw_runtime_digest: str | None = None
    expected_sample_indices: tuple[int, ...] | None = None
    semantic_estimator_id: str = "UNKNOWN"
    semantic_domain_id: str = "UNKNOWN"
    semantic_spacing_id: str = "UNKNOWN"

    def as_dict(self) -> dict[str, Any]:
        indices = self.expected_sample_indices
        if indices is None:
            indices = tuple(range(len(self.expected_sample_ids)))
        return {
            "execution_git_sha": self.execution_git_sha,
            "runner_sha256": self.runner_sha256,
            "scientific_contract_sha256": self.scientific_contract_sha256,
            "plan_semantic_id": self.plan_semantic_id,
            "expected_sample_ids": list(self.expected_sample_ids),
            "raw_runtime_digest": self.raw_runtime_digest,
            "expected_sample_indices": list(indices),
            "semantic_estimator_id": self.semantic_estimator_id,
            "semantic_domain_id": self.semantic_domain_id,
            "semantic_spacing_id": self.semantic_spacing_id,
        }


def _safe_sample_name(sample_id: str) -> str:
    return hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:32] + ".json"


def validate_process_review(review: Mapping[str, Any]) -> None:
    required_document = {"incidents", "pipeline_health", "p0_items", "p1_items", "p2_items"}
    missing = required_document - set(review)
    if missing:
        raise ProcessReviewSchemaError(f"missing document fields: {sorted(missing)}")
    valid_priorities = {"P0", "P1", "P2"}
    required_incident = {
        "incident_id", "phase", "symptom", "root_cause", "occurrence_count",
        "first_detected_when", "recovery_or_workaround",
        "code_or_workflow_change_required", "scientific_result_impact",
        "provenance_impact", "could_have_been_detected_earlier",
        "should_have_been_reported_earlier", "recurrence_risk",
        "permanent_corrective", "priority", "pipeline_defect_candidate",
    }
    seen: set[str] = set()
    for incident in review["incidents"]:
        missing = required_incident - set(incident)
        if missing:
            raise ProcessReviewSchemaError(f"incident missing fields: {sorted(missing)}")
        if incident["priority"] not in valid_priorities:
            raise ProcessReviewSchemaError(
                f"{incident['incident_id']} has invalid priority {incident['priority']!r}"
            )
        if incident["incident_id"] in seen:
            raise ProcessReviewSchemaError(f"duplicate incident {incident['incident_id']}")
        seen.add(incident["incident_id"])
        if "CORRECTIVE_STATUS" in incident and incident["CORRECTIVE_STATUS"] not in {"OPEN", "PARTIALLY_CLOSED", "CLOSED"}:
            raise ProcessReviewSchemaError(f"{incident['incident_id']} has invalid CORRECTIVE_STATUS")


class CampaignRuntime:
    """Generic parent-side campaign runtime; worker execution is injected."""

    ARTIFACT_SCHEMA = "trilatt_campaign_worker_artifact_v1"
    CHECKPOINT_SCHEMA = "trilatt_campaign_checkpoint_v2"

    def __init__(
        self,
        root: Path,
        identity: CampaignIdentity,
        *,
        runner_path: Path,
        contract_path: Path,
        remote_object_checker: Callable[[str], bool] | None = None,
        local_object_checker: Callable[[str], bool] | None = None,
        repository_path: Path | None = None,
        remote_name: str = "origin",
        remote_ref: str = "refs/heads/sandbox",
        production_mode: bool | None = None,
    ) -> None:
        self.root = Path(root)
        self.identity = identity
        self.runner_path = Path(runner_path)
        self.contract_path = Path(contract_path)
        self.remote_object_checker = remote_object_checker
        self.local_object_checker = local_object_checker
        self.repository_path = Path(repository_path) if repository_path is not None else None
        self.remote_name = remote_name
        self.remote_ref = remote_ref
        self.production_mode = bool(repository_path) if production_mode is None else production_mode
        if self.production_mode and self.repository_path is None:
            raise CampaignRuntimeError("PRODUCTION_REPOSITORY_REQUIRED")
        self.workers = self.root / "workers"
        self.checkpoint_path = self.root / "checkpoint.json"
        self.telemetry: dict[str, Any] = {
            "worker_exit_status": [],
            "retry_count": 0,
            "completed_sample_count": 0,
            "rejected_stale_artifact_count": 0,
            "checkpoint_generation_count": 0,
            "worker_failure_count": 0,
            "peak_rss_kib": None,
            "rss_available": False,
        }
        self._preflight_report: dict[str, Any] | None = None

    def _expected_index_map(self) -> dict[str, int]:
        indices = self.identity.expected_sample_indices
        if indices is None:
            indices = tuple(range(len(self.identity.expected_sample_ids)))
        if len(indices) != len(self.identity.expected_sample_ids):
            raise CampaignRuntimeError("EXPECTED_SAMPLE_INDEX_COUNT_MISMATCH")
        return dict(zip((str(value) for value in self.identity.expected_sample_ids), indices))

    def _validate_plan_rows(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        expected = self._expected_index_map()
        if len(rows) != len(expected):
            raise CampaignRuntimeError("PLAN_ROW_COUNT_MISMATCH")
        ids = [str(row.get("sample_id")) for row in rows]
        if len(ids) != len(set(ids)):
            raise CampaignRuntimeError("DUPLICATE_SAMPLE_ID")
        indices = [row.get("sample_index") for row in rows]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in indices):
            raise CampaignRuntimeError("INVALID_SAMPLE_INDEX")
        if len(indices) != len(set(indices)):
            raise CampaignRuntimeError("DUPLICATE_SAMPLE_INDEX")
        if set(ids) != set(expected):
            raise CampaignRuntimeError("SAMPLE_SET_MISMATCH")
        mapping: dict[str, Mapping[str, Any]] = {}
        for row, sample_id in zip(rows, ids):
            if int(row["sample_index"]) != expected[sample_id]:
                raise CampaignRuntimeError("SAMPLE_INDEX_MAPPING_MISMATCH")
            declared = _authoritative_coordinate(row)
            if declared is None:
                raise CampaignRuntimeError("AUTHORITATIVE_COORDINATE_REQUIRED")
            worker = _worker_coordinate(row)
            if worker is not None and worker[1] != declared[1]:
                raise CampaignRuntimeError("WORKER_COORDINATE_SEMANTIC_MISMATCH")
            mapping[sample_id] = row
        return mapping

    def _computed_plan_semantic_id(self, rows: Sequence[Mapping[str, Any]]) -> str:
        return semantic_plan_fingerprint(
            rows,
            estimator_id=self.identity.semantic_estimator_id,
            semantic_domain_id=self.identity.semantic_domain_id,
            spacing_id=self.identity.semantic_spacing_id,
        )

    def _git_output(self, args: Sequence[str]) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=self.repository_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CampaignPreflightError(f"GIT_COMMAND_FAILED:{args[0]}") from exc
        return completed.stdout.strip()

    def _derive_production_state(self, plan_rows: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
        if plan_rows is None:
            raise CampaignPreflightError("PLAN_ROWS_REQUIRED_FOR_PRODUCTION_PREFLIGHT")
        self._validate_plan_rows(plan_rows)
        plan_id = self._computed_plan_semantic_id(plan_rows)
        head = self._git_output(["rev-parse", "HEAD"])
        self._git_output(["cat-file", "-e", f"{self.identity.execution_git_sha}^{{commit}}"])
        dirty = bool(self._git_output(["status", "--porcelain", "--untracked-files=all"]))
        remote_lines = self._git_output(["ls-remote", "--heads", self.remote_name, self.remote_ref]).splitlines()
        if not remote_lines:
            raise CampaignPreflightError("REMOTE_SANDBOX_REF_MISSING")
        remote_head = remote_lines[0].split()[0]
        self._git_output(["fetch", "--quiet", self.remote_name, self.remote_ref])
        fetched_head = self._git_output(["rev-parse", "FETCH_HEAD"])
        if fetched_head != remote_head:
            raise CampaignPreflightError("REMOTE_HEAD_CHANGED_DURING_PREFLIGHT")
        try:
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", self.identity.execution_git_sha, remote_head],
                cwd=self.repository_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CampaignPreflightError("EXECUTION_SHA_NOT_REACHABLE_FROM_REMOTE") from exc
        return {
            "current_execution_sha": head,
            "dirty": dirty,
            "current_plan_semantic_id": plan_id,
            "remote_head_sha": remote_head,
            "remote_ancestry_verified": True,
        }

    def preflight(
        self,
        *,
        current_execution_sha: str | None = None,
        dirty: bool | None = None,
        current_plan_semantic_id: str | None = None,
        remote_execution_object_verified: bool | None = None,
        plan_rows: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        expected = self.identity
        failures: list[str] = []
        state: dict[str, Any] = {
            "current_execution_sha": current_execution_sha,
            "dirty": dirty,
            "current_plan_semantic_id": current_plan_semantic_id,
            "remote_head_sha": None,
            "remote_ancestry_verified": False,
        }
        if self.production_mode:
            try:
                state = self._derive_production_state(plan_rows)
            except CampaignPreflightError as exc:
                failures.append(str(exc))
        else:
            if self.local_object_checker is None:
                failures.append("LOCAL_OBJECT_VERIFIER_REQUIRED")
            elif not self.local_object_checker(expected.execution_git_sha):
                failures.append("LOCAL_EXECUTION_OBJECT_MISSING")
            if not current_execution_sha or current_execution_sha != expected.execution_git_sha:
                failures.append("EXECUTION_GIT_SHA_MISMATCH")
            if dirty:
                failures.append("EXECUTION_SOURCE_DIRTY")
            if current_plan_semantic_id != expected.plan_semantic_id:
                failures.append("PLAN_SEMANTIC_ID_MISMATCH")
            if self.remote_object_checker is None:
                failures.append("REMOTE_OBJECT_VERIFIER_REQUIRED")
            elif not self.remote_object_checker(expected.execution_git_sha):
                failures.append("REMOTE_EXECUTION_OBJECT_MISSING")
        if state["current_execution_sha"] != expected.execution_git_sha:
            failures.append("EXECUTION_GIT_SHA_MISMATCH")
        if state["dirty"]:
            failures.append("EXECUTION_SOURCE_DIRTY")
        if state["current_plan_semantic_id"] != expected.plan_semantic_id:
            failures.append("PLAN_SEMANTIC_ID_MISMATCH")
        if not self.runner_path.is_file() or sha256_file(self.runner_path) != expected.runner_sha256:
            failures.append("RUNNER_SHA256_MISMATCH")
        if not self.contract_path.is_file() or sha256_file(self.contract_path) != expected.scientific_contract_sha256:
            failures.append("SCIENTIFIC_CONTRACT_SHA256_MISMATCH")
        remote_ok = state["remote_ancestry_verified"] if self.production_mode else (
            self.remote_object_checker is not None and self.remote_object_checker(expected.execution_git_sha)
        )
        if self.production_mode and not remote_ok:
            failures.append("REMOTE_EXECUTION_OBJECT_MISSING")
        report = {
            "status": "REMOTE_EXECUTION_OBJECT_VERIFIED" if self.production_mode and not failures else (
                "TEST_VERIFIER_ACCEPTED" if not failures else "PREFLIGHT_REJECTED"
            ),
            "failures": sorted(set(failures)),
            "identity": expected.as_dict(),
            "execution_sha": state["current_execution_sha"],
            "dirty": state["dirty"],
            "plan_semantic_id": state["current_plan_semantic_id"],
            "remote_name": self.remote_name,
            "remote_ref": self.remote_ref,
            "remote_head_sha": state["remote_head_sha"],
            "remote_ancestry_verified": bool(state["remote_ancestry_verified"]),
            "remote_execution_object_verified": bool(remote_ok),
            "preflight_mode": "PRODUCTION_GIT" if self.production_mode else "TEST_VERIFIER",
            "worker_launch_authorized": not failures,
        }
        if failures:
            raise CampaignPreflightError(json.dumps(report, sort_keys=True))
        self._preflight_report = report
        return report

    def _artifact_path(self, sample_id: str) -> Path:
        return self.workers / _safe_sample_name(sample_id)

    def _validate_artifact(self, artifact: Mapping[str, Any], *, sample_id: str, sample_index: int) -> None:
        expected = self.identity
        checks = {
            "schema": (artifact.get("schema"), self.ARTIFACT_SCHEMA),
            "execution_git_sha": (artifact.get("execution_git_sha"), expected.execution_git_sha),
            "runner_sha256": (artifact.get("runner_sha256"), expected.runner_sha256),
            "scientific_contract_sha256": (artifact.get("scientific_contract_sha256"), expected.scientific_contract_sha256),
            "plan_semantic_id": (artifact.get("plan_semantic_id"), expected.plan_semantic_id),
            "sample_id": (artifact.get("sample_id"), sample_id),
            "sample_index": (artifact.get("sample_index"), sample_index),
            "completion_status": (artifact.get("completion_status"), "COMPLETE"),
        }
        for key, (actual, wanted) in checks.items():
            if actual != wanted:
                raise ArtifactValidationError(f"{key}_MISMATCH:{actual!r}!={wanted!r}")

    def publish_worker_artifact(self, *, sample_id: str, sample_index: int, result: Mapping[str, Any]) -> Path:
        if self._preflight_report is None:
            raise CampaignPreflightError("PREFLIGHT_REQUIRED_BEFORE_WORKER")
        expected_indices = self._expected_index_map()
        if sample_id not in expected_indices:
            raise ArtifactValidationError(f"UNKNOWN_SAMPLE_ID:{sample_id}")
        if sample_index != expected_indices[sample_id]:
            raise ArtifactValidationError(
                f"SAMPLE_INDEX_MISMATCH:{sample_index}!={expected_indices[sample_id]}"
            )
        path = self._artifact_path(sample_id)
        if path.exists():
            raise ArtifactValidationError(f"DUPLICATE_SAMPLE:{sample_id}")
        payload = dict(result)
        expected_fields = {
            "schema": self.ARTIFACT_SCHEMA,
            "execution_git_sha": self.identity.execution_git_sha,
            "runner_sha256": self.identity.runner_sha256,
            "scientific_contract_sha256": self.identity.scientific_contract_sha256,
            "plan_semantic_id": self.identity.plan_semantic_id,
            "sample_id": sample_id,
            "sample_index": sample_index,
            "completion_status": "COMPLETE",
        }
        for key, expected_value in expected_fields.items():
            if key in payload and payload[key] != expected_value:
                raise ArtifactValidationError(f"{key}_MISMATCH:{payload[key]!r}!={expected_value!r}")
        payload.update(expected_fields)
        self._validate_artifact(payload, sample_id=sample_id, sample_index=sample_index)
        atomic_json_write(path, payload)
        self.telemetry["worker_exit_status"].append({"sample_id": sample_id, "status": 0})
        self.telemetry["peak_rss_kib"] = current_rss_kib()
        self.telemetry["rss_available"] = self.telemetry["peak_rss_kib"] is not None
        return path

    def load_completed_artifacts(self, rows: Sequence[Mapping[str, Any]]) -> set[str]:
        expected = self._validate_plan_rows(rows)
        completed: set[str] = set()
        self.workers.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.workers.glob("*.json")):
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.telemetry["rejected_stale_artifact_count"] += 1
                raise ArtifactValidationError(f"CORRUPT_WORKER_ARTIFACT:{path.name}") from exc
            sample_id = artifact.get("sample_id")
            if sample_id not in expected:
                self.telemetry["rejected_stale_artifact_count"] += 1
                continue
            self._validate_artifact(
                artifact,
                sample_id=sample_id,
                sample_index=int(expected[sample_id]["sample_index"]),
            )
            if sample_id in completed:
                raise ArtifactValidationError(f"DUPLICATE_SAMPLE:{sample_id}")
            completed.add(sample_id)
        self.telemetry["completed_sample_count"] = len(completed)
        return completed

    def _artifact_binding(self, sample_id: str, sample_index: int) -> dict[str, Any]:
        path = self._artifact_path(sample_id)
        if not path.is_file():
            raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_MISSING:{sample_id}")
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_CORRUPT:{sample_id}") from exc
        try:
            self._validate_artifact(artifact, sample_id=sample_id, sample_index=sample_index)
        except ArtifactValidationError as exc:
            raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_INVALID:{sample_id}") from exc
        return {
            "sample_index": sample_index,
            "sha256": sha256_file(path),
            "schema": artifact["schema"],
        }

    def write_checkpoint(self, completed_sample_ids: Iterable[str]) -> Path:
        completed = sorted(set(completed_sample_ids))
        expected = sorted(self.identity.expected_sample_ids)
        expected_indices = self._expected_index_map()
        if not set(completed).issubset(set(expected)):
            raise CheckpointValidationError("CHECKPOINT_HAS_UNKNOWN_SAMPLE")
        completed_artifacts = {
            sample_id: self._artifact_binding(sample_id, expected_indices[sample_id])
            for sample_id in completed
        }
        generation = int(self.telemetry["checkpoint_generation_count"]) + 1
        checkpoint_telemetry = dict(self.telemetry)
        checkpoint_telemetry["checkpoint_generation_count"] = generation
        payload = {
            "schema": self.CHECKPOINT_SCHEMA,
            "identity": self.identity.as_dict(),
            "expected_sample_ids": expected,
            "completed_sample_ids": completed,
            "completed_artifacts": completed_artifacts,
            "telemetry": checkpoint_telemetry,
            "generation": generation,
        }
        atomic_json_write(self.checkpoint_path, payload)
        self.telemetry.update(checkpoint_telemetry)
        return self.checkpoint_path

    def load_checkpoint(self) -> set[str]:
        if not self.checkpoint_path.exists():
            return set()
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointValidationError("CORRUPT_CHECKPOINT") from exc
        if payload.get("schema") != self.CHECKPOINT_SCHEMA:
            raise CheckpointValidationError("CHECKPOINT_SCHEMA_MISMATCH")
        if payload.get("identity") != self.identity.as_dict():
            raise CheckpointValidationError("CHECKPOINT_IDENTITY_MISMATCH")
        if sorted(payload.get("expected_sample_ids", [])) != sorted(self.identity.expected_sample_ids):
            raise CheckpointValidationError("CHECKPOINT_SAMPLE_SET_MISMATCH")
        completed = payload.get("completed_sample_ids")
        if not isinstance(completed, list) or len(completed) != len(set(completed)):
            raise CheckpointValidationError("CHECKPOINT_COMPLETION_DUPLICATE")
        if not set(completed).issubset(set(self.identity.expected_sample_ids)):
            raise CheckpointValidationError("CHECKPOINT_UNKNOWN_SAMPLE")
        bindings = payload.get("completed_artifacts")
        if not isinstance(bindings, dict) or set(bindings) != set(completed):
            raise CheckpointValidationError("CHECKPOINT_ARTIFACT_BINDING_SET_MISMATCH")
        expected_indices = self._expected_index_map()
        for sample_id in completed:
            binding = bindings.get(sample_id)
            if not isinstance(binding, dict):
                raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_BINDING_INVALID:{sample_id}")
            if binding.get("sample_index") != expected_indices[sample_id]:
                raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_INDEX_MISMATCH:{sample_id}")
            actual = self._artifact_binding(sample_id, expected_indices[sample_id])
            if actual["sha256"] != binding.get("sha256"):
                raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_HASH_MISMATCH:{sample_id}")
            if actual["schema"] != binding.get("schema"):
                raise CheckpointValidationError(f"CHECKPOINT_ARTIFACT_SCHEMA_MISMATCH:{sample_id}")
        generation = payload.get("generation")
        telemetry = payload.get("telemetry")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise CheckpointValidationError("CHECKPOINT_GENERATION_INVALID")
        if not isinstance(telemetry, dict):
            raise CheckpointValidationError("CHECKPOINT_TELEMETRY_INVALID")
        telemetry_generation = telemetry.get("checkpoint_generation_count")
        if isinstance(telemetry_generation, bool) or telemetry_generation != generation:
            raise CheckpointValidationError("CHECKPOINT_GENERATION_INCONSISTENT")
        self.telemetry.update(telemetry)
        return set(completed)

    def run(self, rows: Sequence[Mapping[str, Any]], worker: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
        if self._preflight_report is None:
            raise CampaignPreflightError("PREFLIGHT_REQUIRED_BEFORE_WORKER")
        self._validate_plan_rows(rows)
        if self._computed_plan_semantic_id(rows) != self.identity.plan_semantic_id:
            raise CampaignRuntimeError("PLAN_SEMANTIC_ID_MISMATCH")
        artifact_completed = self.load_completed_artifacts(rows)
        checkpoint_completed = self.load_checkpoint()
        completed = artifact_completed | checkpoint_completed
        for row in rows:
            sample_id = str(row["sample_id"])
            if sample_id in completed:
                continue
            try:
                result = worker(row)
                self.publish_worker_artifact(
                    sample_id=sample_id,
                    sample_index=int(row["sample_index"]),
                    result=result,
                )
            except Exception:
                self.telemetry["worker_failure_count"] += 1
                raise
            completed.add(sample_id)
            self.write_checkpoint(completed)
            checkpoint_completed = set(completed)
        if completed != checkpoint_completed:
            self.write_checkpoint(completed)
        self.telemetry["completed_sample_count"] = len(completed)
        return {
            "status": "COMPLETE" if len(completed) == len(rows) else "INCOMPLETE",
            "completed_sample_ids": sorted(completed),
            "telemetry": self.telemetry,
        }


def run_worker_command(command: Sequence[str], *, timeout_seconds: float = 60.0) -> dict[str, Any]:
    """Run one bounded worker process and parse its JSON stdout.

    The parent remains solver-agnostic; callers inject the command. A non-zero
    exit, timeout, or non-JSON result is never treated as completed science.
    """
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout_seconds)
        value = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise CampaignRuntimeError(f"WORKER_COMMAND_FAILED:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise CampaignRuntimeError("WORKER_COMMAND_RESULT_NOT_OBJECT")
    return value


def resolve_sibling_repo(current_repo: Path, sibling_name: str, *, configured_root: Path | None = None) -> Path:
    root = Path(configured_root) if configured_root is not None else Path(current_repo).resolve().parent
    candidate = root / sibling_name
    if not candidate.is_dir():
        raise CampaignRuntimeError(f"SIBLING_REPOSITORY_NOT_FOUND:{candidate}")
    return candidate
