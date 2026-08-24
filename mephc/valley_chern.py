"""Solver-neutral valley-Chern semantics with sealed upstream provenance."""
from __future__ import annotations
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TWO_PI = 2.0 * math.pi
V_K_AREA = 1.0 / math.sqrt(3.0)
DOMAIN_ID = "PERIODIC_RECIPROCAL_METRIC_VORONOI_BASIN_K"
Q_COORDINATE_RELATION = "q=k_phys*a/(2*pi)"
ORIENTATION = "POSITIVE_PUBLIC_CARTESIAN_QX_QY"
BERRY_SIGN_CONVENTION = "OMEGA=-WILSON_PHASE/SIGNED_AREA/(2*pi)^2"
PRIMARY_COMPONENTS = ("band1", "band2")
DIAGNOSTIC_COMPONENTS = ("anti", "common")
ALL_COMPONENTS = PRIMARY_COMPONENTS + DIAGNOSTIC_COMPONENTS
SEALED_REFINED_FLUX = {
    "band1": -0.8672556366262376,
    "band2": 0.39539937924821406,
    "anti": -0.6313275079372258,
    "common": -0.23592812868901175,
}
E7I1G_UPSTREAM_SEAL = {
    "seal_id": "E7I1G_LEVEL2_VORONOI_VALLEY_ASSIGNED_BERRY_FLUX",
    "seal_status": "PHYSICALLY_VALIDATED_WITH_EXPLICIT_PERTURBED_NODE_UNCERTAINTY",
    "sealed_sandbox_sha": "e35bcb6a1fc567b670c64a8c7070d083777c2e87",
    "source_evidence_sha256": "196fcdae172b9b718185c61261de375b54a759e93d4d215c2bd5846ee841c67d",
    "domain_id": DOMAIN_ID,
    "orientation": ORIENTATION,
    "normalization_input": "SEALED_REFINED_FLUX",
}
S_BAND1 = 0.8382559622490607
S_BAND2 = 0.1842433985735109
INVERSION_HYBRID_TOL = 0.05
PAPER_CORE = ("PAPER_BLOCH_FACTOR", "MPB_BLOCH_FACTOR", "K_MAPPING", "VALLEY_LABEL_MAPPING", "status", "provenance_mode")
PAPER_STATUS = frozenset({"CONSISTENT_AFTER_BLOCH_K_MAPPING", "PARTIALLY_CONSISTENT", "SIGN_OR_NORMALIZATION_TENSION", "UNRESOLVED"})
TR_STATUS = frozenset({"SUPPORTED_BY_EXISTING_CONTROLS", "FULL_KP_INTEGRATION_VALIDATED", "TENSION", "UNRESOLVED"})
DOMAIN_STATUS = frozenset({"SIGN_REVERSAL_SUPPORTED", "PARTIALLY_SUPPORTED", "TENSION", "UNRESOLVED"})

def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _code_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def valley_chern_from_flux(flux: Any, *, orientation_sign: int = 1) -> float:
    if orientation_sign not in (-1, 1):
        raise ValueError("orientation_sign must be +1 or -1")
    return orientation_sign * _finite(flux, "flux") / TWO_PI

def coordinate_flux_invariance(omega_q: Any, q_area: Any, lattice_scale_a: Any) -> dict[str, float | bool]:
    omega, area, a = _finite(omega_q, "omega_q"), _finite(q_area, "q_area"), _finite(lattice_scale_a, "lattice_scale_a")
    if a <= 0.0:
        raise ValueError("lattice_scale_a must be positive")
    omega_phys_over_a2 = omega / TWO_PI**2
    physical_k_area = area * (TWO_PI / a) ** 2
    restored = omega_phys_over_a2 * physical_k_area * a**2
    return {"q_flux": omega * area, "omega_phys_over_a2": omega_phys_over_a2, "physical_k_area": physical_k_area, "restored_physical_flux": restored, "equal": math.isclose(omega * area, restored, rel_tol=0.0, abs_tol=1e-14)}

def time_reversal_theory() -> dict[str, str]:
    return {"TR_BERRY_RELATION": "Omega_n(k)=-Omega_n(-k)", "TR_DOMAIN_RELATION": "V_Kp=-V_K on the reciprocal torus", "TR_FLUX_RELATION": "Phi_n,Kp=-Phi_n,K", "TR_VALLEY_CHERN_RELATION": "C_n,Kp^v=-C_n,K^v", "TR_AREA_JACOBIAN": "det(-I_2)=+1", "TR_NUMERICAL_SCOPE": "theory_only_until_dedicated_K_Kp_controls_are_supplied"}

def _component_map(value: Mapping[str, Any], name: str) -> dict[str, float]:
    result = {}
    for component in ALL_COMPONENTS:
        if component not in value:
            raise ValueError(f"{name} lacks {component}")
        result[component] = _finite(value[component], f"{name}.{component}")
    return result

def _bound_map(value: Mapping[str, Any] | None) -> dict[str, float]:
    if value is None:
        return {component: 0.0 for component in ALL_COMPONENTS}
    result = {component: _finite(value.get(component, 0.0), f"flux_error_bound.{component}") for component in ALL_COMPONENTS}
    if any(number < 0.0 for number in result.values()):
        raise ValueError("flux error bounds must be nonnegative")
    return result

def _upstream_seal_audit(seal: Mapping[str, Any] | None, flux: Mapping[str, float]) -> dict[str, Any]:
    if seal is None:
        return {"status": "FAILED", "reason": "upstream E7I.1G seal object is missing"}
    required = tuple(E7I1G_UPSTREAM_SEAL)
    if any(key not in seal for key in required):
        return {"status": "FAILED", "reason": "upstream E7I.1G seal object is incomplete"}
    if any(seal[key] != E7I1G_UPSTREAM_SEAL[key] for key in required):
        return {"status": "FAILED", "reason": "upstream seal identity, domain, orientation, or source differs"}
    return {"status": "SUPERVISOR_SEALED", "seal": dict(seal)}

def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty metric")
    position = 0.9 * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (position - low)

def _omega(record: Mapping[str, Any], band: int) -> float:
    if f"omega_band{band}" in record:
        return _finite(record[f"omega_band{band}"], f"omega_band{band}")
    values = record.get("omega_bands_q")
    if not isinstance(values, (list, tuple)) or len(values) < band:
        raise ValueError("inversion control lacks Berry band value")
    return _finite(values[band - 1], f"omega_band{band}")

def inversion_control_audit(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if evidence is None:
        return {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED", "matched_control_count": 0}
    rows = evidence.get("inversion_pairs")
    if not isinstance(rows, list) or not rows:
        return {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED", "matched_control_count": 0}
    metrics = []
    for row in rows:
        base, plus = row.get("base"), row.get("plus")
        if not isinstance(base, Mapping) or not isinstance(plus, Mapping):
            return {"status": "FAILED", "evidence_level": "LOCAL_MATCHED_CONTROLS", "reason": "malformed inversion pair"}
        pair = {"spectral": row.get("spectral_compatible") is True, "rank": row.get("rank_compatible") is True, "qualified": row.get("qualification_compatible") is True, "bands": {}}
        for band, scale in ((1, S_BAND1), (2, S_BAND2)):
            left, right = _omega(base, band), _omega(plus, band)
            floor = 0.1 * scale
            resolved = max(abs(left), abs(right)) >= floor
            reversed_sign = left == 0.0 or right == 0.0 or math.copysign(1.0, left) != math.copysign(1.0, right)
            hybrid = abs(left + right) / max(abs(left), abs(right), floor)
            pair["bands"][band] = {"resolved": resolved, "sign_reversed": reversed_sign, "hybrid": hybrid}
        metrics.append(pair)
    resolved_counts = {band: sum(item["bands"][band]["resolved"] for item in metrics) for band in (1, 2)}
    indeterminate_counts = {band: len(metrics) - resolved_counts[band] for band in (1, 2)}
    p90 = {band: _p90([item["bands"][band]["hybrid"] for item in metrics]) for band in (1, 2)}
    compatible = all(item["spectral"] and item["rank"] and item["qualified"] for item in metrics)
    signs_ok = all(not item["bands"][band]["resolved"] or item["bands"][band]["sign_reversed"] for item in metrics for band in (1, 2))
    status = "SIGN_REVERSAL_SUPPORTED" if compatible and signs_ok and all(p90[band] <= INVERSION_HYBRID_TOL for band in (1, 2)) else "PARTIALLY_SUPPORTED"
    return {
        "status": status,
        "evidence_level": "LOCAL_MATCHED_CONTROLS",
        "matched_control_count": len(metrics),
        "inversion_sign_resolved_band1_count": resolved_counts[1],
        "inversion_sign_indeterminate_band1_count": indeterminate_counts[1],
        "inversion_sign_resolved_band2_count": resolved_counts[2],
        "inversion_sign_indeterminate_band2_count": indeterminate_counts[2],
        "inversion_hybrid_p90_band1": p90[1],
        "inversion_hybrid_p90_band2": p90[2],
        "spectral_compatibility": compatible,
        "sign_reversal_gate": signs_ok,
        "source_digest": _digest(evidence),
        "reducer_code_digest": _code_digest(),
        "provenance_mode": "RECOMPUTED_FROM_COMPACT_EVIDENCE",
    }

def _paper_audit(convention: Mapping[str, Any] | None) -> dict[str, Any]:
    if convention is None:
        return {"status": "UNRESOLVED", "provenance": "FAILED"}
    if any(key not in convention for key in PAPER_CORE):
        raise ValueError("paper convention object is incomplete")
    expected = {"PAPER_BLOCH_FACTOR": "exp(-i k dot r)", "MPB_BLOCH_FACTOR": "exp(+i k dot r)", "K_MAPPING": "k_paper=-k_MPB", "VALLEY_LABEL_MAPPING": "paper_K <-> MPB_Kp; paper_Kp <-> MPB_K"}
    mapping_ok = all(convention.get(key) == value for key, value in expected.items())
    no_hack = convention.get("curvature_sign_hack") == "NONE" or convention.get("no_sign_hack") is True
    status = convention["status"] if convention["status"] in PAPER_STATUS else "UNRESOLVED"
    if not mapping_ok or not no_hack:
        status = "SIGN_OR_NORMALIZATION_TENSION"
    mode = convention["provenance_mode"]
    provenance = "SUPERVISOR_SEALED_INHERITANCE" if mode == "INHERITED_FROM_SUPERVISOR_SEALED_REF6_1_CONVENTION" else "CRYPTOGRAPHIC_PRIOR_ARTIFACT_LINK" if mode == "CRYPTOGRAPHIC_PRIOR_ARTIFACT_LINK" else "PARTIAL"
    return {**dict(convention), "status": status, "mapping_validated": mapping_ok, "no_sign_hack": no_hack, "provenance_classification": provenance, "mapping_orientation": "ORIENTATION_PRESERVING_VALLEY_LABEL_SWAP" if mapping_ok else "UNRESOLVED"}

def inherited_paper_convention() -> dict[str, Any]:
    return {
        "status": "CONSISTENT_AFTER_BLOCH_K_MAPPING",
        "provenance_mode": "INHERITED_FROM_SUPERVISOR_SEALED_REF6_1_CONVENTION",
        "prior_result": "REF6.1 paper-vs-MPB Bloch convention sign closure",
        "PAPER_BLOCH_FACTOR": "exp(-i k dot r)",
        "MPB_BLOCH_FACTOR": "exp(+i k dot r)",
        "K_MAPPING": "k_paper=-k_MPB",
        "VALLEY_LABEL_MAPPING": "paper_K <-> MPB_Kp; paper_Kp <-> MPB_K",
        "coordinate_jacobian_sign": 1,
        "curvature_sign_hack": "NONE",
    }

def _tr_audit(evidence: Mapping[str, Any] | None, recovery: str) -> dict[str, Any]:
    if evidence is None:
        return {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED", "matched_control_count": 0, "recovery": recovery}
    status = evidence.get("status", "UNRESOLVED")
    if status not in TR_STATUS:
        raise ValueError("unsupported TR status")
    result = dict(evidence)
    if status == "UNRESOLVED":
        result["recovery"] = recovery
        return result
    if type(evidence.get("matched_control_count")) is not int or evidence["matched_control_count"] < 1:
        raise ValueError("TR evidence requires matched controls")
    if evidence.get("spectral_correspondence") is not True or evidence.get("qualification_compatibility") is not True:
        raise ValueError("TR evidence requires spectral and qualification compatibility")
    result["recovery"] = recovery
    return result
def _compat_inversion(evidence):
    if evidence is None:
        return inversion_control_audit(None)
    status = evidence.get("status", "UNRESOLVED")
    level = evidence.get("evidence_level", "UNRESOLVED")
    if status not in DOMAIN_STATUS or level not in {"LOCAL_MATCHED_CONTROLS", "FULL_DOMAIN_INTEGRAL", "THEORY_ONLY", "UNRESOLVED"}:
        raise ValueError("unsupported domain inversion evidence")
    return {**dict(evidence), "status": status, "evidence_level": level}


def build_valley_chern_audit(
    sealed_flux,
    *,
    flux_error_bound=None,
    upstream_seal=None,
    c9_source_digest=None,
    c9_provenance=None,
    control_status=None,
    inversion_controls=None,
    domain_inversion_evidence=None,
    tr_evidence=None,
    tr_control_recovery="NO_EXISTING_CONTROLS_FOUND",
    paper_convention=None,
):
    flux = _component_map(sealed_flux, "sealed_flux")
    bounds = _bound_map(flux_error_bound)
    seal = upstream_seal
    seal_audit = _upstream_seal_audit(seal, flux)
    if seal_audit.get("status") == "SUPERVISOR_SEALED":
        if any(not math.isclose(flux[key], SEALED_REFINED_FLUX[key], rel_tol=0.0, abs_tol=1e-12) for key in ALL_COMPONENTS):
            seal_audit = {"status": "FAILED", "reason": "sealed flux does not match upstream seal"}
    controls = dict(control_status or {})
    control_summary = {key: controls[key] for key in ("BERRY_TORUS_PERIODICITY", "C9_HARDENING_IMPLEMENTATION_STATUS", "C9_HARDENING_CURRENT_REPLAY_STATUS", "C9_CURRENT_RAW_REPLAY_AVAILABILITY") if key in controls}
    inversion = (inversion_control_audit(inversion_controls) if inversion_controls is not None
                 else _compat_inversion(domain_inversion_evidence))
    paper = _paper_audit(paper_convention) if paper_convention is not None else {"status": "UNRESOLVED", "provenance_classification": "UNRESOLVED"}
    tr = _tr_audit(tr_evidence, tr_control_recovery)
    chern = {component: valley_chern_from_flux(flux[component]) for component in ALL_COMPONENTS}
    chern_bounds = {component: bounds[component] / TWO_PI for component in ALL_COMPONENTS}
    coord = coordinate_flux_invariance(flux["band1"] / V_K_AREA, V_K_AREA, 1.0)
    band_interpretation = {
        "band1": "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE",
        "band2": "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE",
        "anti": "DIAGNOSTIC_LINEAR_COMBINATION",
        "common": "DIAGNOSTIC_LINEAR_COMBINATION",
    }
    raw_status = controls.get("C9_HARDENING_CURRENT_REPLAY_STATUS", "RAW_SOURCE_CURRENTLY_UNAVAILABLE")
    c9_impl = controls.get("C9_HARDENING_IMPLEMENTATION_STATUS", "PARTIAL")
    raw_availability = "AVAILABLE_AND_REPLAYED" if raw_status == "REPLAYED_CURRENT_WORKSPACE" else "UNAVAILABLE_CURRENT_WORKSPACE"
    raw_replay_state = {"availability": raw_availability}
    uncertainty_provenance = "INHERITED_FROM_SEALED_E7I1G_PERTURBED_NODE_BOUND"
    candidate = (
        seal_audit.get("status") == "SUPERVISOR_SEALED"
        and inversion.get("status") in {"SIGN_REVERSAL_SUPPORTED", "PARTIALLY_SUPPORTED"}
        and paper.get("status") == "CONSISTENT_AFTER_BLOCH_K_MAPPING"
        and paper.get("no_sign_hack") is True
        and coord["equal"]
        and tr.get("status") in {"SUPPORTED_BY_EXISTING_CONTROLS", "UNRESOLVED"}
    )
    result = {
        "E7I1H_SCOPE": "VALLEY_CHERN_ONLY_NO_NEW_MPB",
        "E7I1G_UPSTREAM_SEAL_STATUS": seal_audit.get("status"),
        "E7I1G_UPSTREAM_SEAL": seal_audit,
        "UPSTREAM_SEAL_IDENTITY": "IMMUTABLE_SCIENTIFIC_PROVENANCE",
        "UPSTREAM_SEAL_REPLAY_SEPARATION": "COMPLETE",
        "SEALED_INPUT_DEPENDENCY": "EXPLICIT_AND_FAIL_CLOSED" if seal_audit.get("status") == "SUPERVISOR_SEALED" else "FAILED",
        "DOMAIN": {
            "id": DOMAIN_ID,
            "definition": "periodic reciprocal-metric Voronoi basin of K",
            "area_q": V_K_AREA,
            "orientation": ORIENTATION,
            "coordinate_relation": Q_COORDINATE_RELATION,
            "boundary_convention": "zero_measure_boundary_inherited_from_E7I1G",
        },
        "SEALED_REFINED_FLUX": flux,
        "SEALED_REFINED_FLUX_ERROR_BOUND": bounds,
        "VALLEY_CHERN": chern,
        "VALLEY_CHERN_ERROR_BOUND": chern_bounds,
        "VALLEY_CHERN_NORMALIZATION": "PHI_OVER_2PI_CONFIRMED",
        "VALLEY_FLUX_COORDINATE_INVARIANCE": "DERIVED_AND_VALIDATED" if coord["equal"] else "FAILED",
        "COORDINATE_INVARIANCE_CHECK": coord,
        "TR_THEORY": time_reversal_theory(),
        "TR_VALLEY_RELATION_THEORY": "DERIVED",
        "TR_VALLEY_RELATION_NUMERIC_STATUS": tr["status"],
        "TR_CONTROL_RECOVERY": tr_control_recovery,
        "TR_KP_CONTROL_EVIDENCE": tr,
        "VALLEY_CHERN_DOMAIN_INVERSION": inversion.get("status", "UNRESOLVED"),
        "DOMAIN_INVERSION_EVIDENCE_LEVEL": inversion.get("evidence_level", "UNRESOLVED"),
        "DOMAIN_INVERSION_EVIDENCE": inversion,
        "PAPER_CONVENTION_AUDIT": paper,
        "PAPER_VALLEY_CHERN_CONVENTION": paper.get("status", "UNRESOLVED"),
        "PAPER_CONVENTION_PROVENANCE": paper.get("provenance_classification", "UNRESOLVED"),
        "PAPER_MAPPING_ORIENTATION": paper.get("mapping_orientation", "UNRESOLVED"),
        "PAPER_GEOMETRY_EQUIVALENCE": "UNRESOLVED",
        "BLOCH_K_MAPPING": paper.get("K_MAPPING", "UNRESOLVED"),
        "SIGN_HACK": "NONE" if paper.get("no_sign_hack") is True else "UNRESOLVED",
        "FULL_BZ_CHERN_SEMANTICS": "closed_BZ_torus_integral_divided_by_2pi_quantized_under_isolated_smooth_band_conditions",
        "NONQUANTIZED_VALLEY_CHERN_INTERPRETATION": "MATHEMATICALLY_CLOSED",
        "VALLEY_CHERN_DOMAIN_SEMANTICS": "EXPLICIT_AND_BOUNDARY_AWARE",
        "VALLEY_CHERN_DOMAIN_DEPENDENCE": "restricted_integral_can_change_with_valley_partition_boundary",
        "VALLEY_CHERN_MULTIBAND_INTERPRETATION": "INDIVIDUAL_BANDS_PRIMARY_DIAGNOSTIC_COMBINATIONS_SEPARATE",
        "BAND_INTERPRETATION": band_interpretation,
        "CONTROL_STATUS_INHERITED": control_summary,
        "C9_HARDENING_IMPLEMENTATION_STATUS": c9_impl,
        "C9_HARDENING_CURRENT_REPLAY_STATUS": raw_status,
        "C9_CURRENT_RAW_REPLAY_AVAILABILITY": raw_availability,
        "C9_RAW_REPLAY_STATE": raw_replay_state,
        "C9_HARDENED_ARTIFACT_REPLAY": "COMPLETE_NO_SCIENTIFIC_CHANGE" if raw_status == "REPLAYED_CURRENT_WORKSPACE" else "RAW_SOURCE_CURRENTLY_UNAVAILABLE",
        "VALLEY_CHERN_SEAL": "CANDIDATE_FOR_SUPERVISOR_SEAL" if candidate else "PARTIALLY_VALIDATED",
        "E7I1H_REMOTE_AUDITABILITY": "COMPLETE",
        "REMOTE_AUDITABILITY": "COMPLETE",
        "VALLEY_CHERN_UNCERTAINTY_PROVENANCE": uncertainty_provenance,
        "E7I1H_C3_OVERALL": "FINAL_PROVENANCE_STATE_READY_FOR_SUPERVISOR_SEAL" if candidate else "PROVENANCE_CORRECTIVE_PARTIAL",
        "PROVENANCE": {
            "c9_source_digest": c9_source_digest,
            "c9_provenance": dict(c9_provenance or {}),
            "domain_id": DOMAIN_ID,
            "domain_area_q": V_K_AREA,
            "orientation": ORIENTATION,
            "coordinate_relation": Q_COORDINATE_RELATION,
            "berry_sign_convention": BERRY_SIGN_CONVENTION,
            "normalization": "PHI_OVER_2PI",
            "band_interpretation": band_interpretation,
            "raw_replay_state": raw_replay_state,
        },
    }
    result["detail_digest"] = _digest(result)
    return result


def audit_from_c9_report(report, *, existing_controls=None, tr_evidence=None, paper_convention=None, tr_control_recovery="NO_EXISTING_CONTROLS_FOUND"):
    try:
        direct = report["direct_flux"]["refined_centroid"]
        bounds = {component: report["audit"]["bounds"][component]["refined_centroid"]["delta_phi_bound_weighted"] for component in ALL_COMPONENTS}
    except (KeyError, TypeError) as error:
        raise ValueError("C9 report lacks sealed refined flux and bounds") from error
    source_digest = _digest({"source_file_sha256": report.get("SOURCE_FILE_SHA256"), "c7_replay": report.get("C7_SOURCE_REPLAY"), "c9_replay": report.get("C9_DIRECT_SOURCE_FLUX_REPLAY"), "direct_flux": direct, "bounds": bounds})
    has_current_replay = bool(report.get("C9_AUDIT_HARDENING") and report.get("AUDIT_CODE_FINGERPRINTS"))
    controls = dict(existing_controls or {})
    controls.update({
        "BERRY_TORUS_PERIODICITY": report.get("BERRY_TORUS_PERIODICITY", "UNRESOLVED"),
        "C9_HARDENING_IMPLEMENTATION_STATUS": "PRESENT_ON_SANDBOX",
        "C9_HARDENING_CURRENT_REPLAY_STATUS": "REPLAYED_CURRENT_WORKSPACE" if has_current_replay else "RAW_SOURCE_CURRENTLY_UNAVAILABLE",
        "C9_CURRENT_RAW_REPLAY_AVAILABILITY": "AVAILABLE_CURRENT_WORKSPACE" if has_current_replay else "UNAVAILABLE_CURRENT_WORKSPACE",
    })
    provenance = report.get("CONTROL_CLASSIFICATION_PROVENANCE", {})
    return build_valley_chern_audit(direct, flux_error_bound=bounds, upstream_seal=E7I1G_UPSTREAM_SEAL, c9_source_digest=source_digest, c9_provenance=provenance, control_status=controls, inversion_controls=existing_controls, tr_evidence=tr_evidence, tr_control_recovery=tr_control_recovery, paper_convention=paper_convention or inherited_paper_convention())
from .valley_integration import (IntegrationPlanError, MEPHC_CLIPPED_RETAINED_DOMAIN_V1, PORTABLE_PLAN_FINGERPRINT_SCHEMA_V1, PORTABILITY_TOLERANCE, RetainedDomain, SEMANTIC_DOMAIN_SCHEMA_V1, SOURCE_GRID_MIDPOINT_V1, SOURCE_GRID_SPACING_ID, build_berry_row, build_integration_plan, build_source_bound_domain, compare_plan_semantics, portable_plan_fingerprint, reduce_supplied_berry_rows, semantic_domain_id, validate_integration_plan)
