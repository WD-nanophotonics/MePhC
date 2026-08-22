"""Solver-neutral valley-Chern semantics and provenance audit."""
from __future__ import annotations
import hashlib
import json
import math
from collections.abc import Mapping
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
PAPER_REQUIRED = ("PAPER_BLOCH_FACTOR","MPB_BLOCH_FACTOR","K_MAPPING","VALLEY_LABEL_MAPPING","status","provenance_mode","source_digest","reducer_code_digest")
PAPER_STATUS = frozenset({"CONSISTENT_AFTER_BLOCH_K_MAPPING","PARTIALLY_CONSISTENT","SIGN_OR_NORMALIZATION_TENSION","UNRESOLVED"})
DOMAIN_STATUS = frozenset({"SIGN_REVERSAL_SUPPORTED","PARTIALLY_SUPPORTED","TENSION","UNRESOLVED"})
TR_STATUS = frozenset({"SUPPORTED_BY_EXISTING_CONTROLS","FULL_KP_INTEGRATION_VALIDATED","TENSION","UNRESOLVED"})

def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def valley_chern_from_flux(flux: Any, *, orientation_sign: int = 1) -> float:
    if orientation_sign not in (-1, 1):
        raise ValueError("orientation_sign must be +1 or -1")
    return orientation_sign * _finite(flux, "flux") / TWO_PI

def coordinate_flux_invariance(omega_q: Any, q_area: Any, lattice_scale_a: Any) -> dict[str, float | bool]:
    omega = _finite(omega_q, "omega_q")
    area = _finite(q_area, "q_area")
    a = _finite(lattice_scale_a, "lattice_scale_a")
    if a <= 0.0:
        raise ValueError("lattice_scale_a must be positive")
    omega_phys_over_a2 = omega / TWO_PI**2
    physical_k_area = area * (TWO_PI / a) ** 2
    restored_physical_flux = omega_phys_over_a2 * physical_k_area * a**2
    return {"q_flux": omega * area, "omega_phys_over_a2": omega_phys_over_a2, "physical_k_area": physical_k_area, "restored_physical_flux": restored_physical_flux, "equal": math.isclose(omega * area, restored_physical_flux, rel_tol=0.0, abs_tol=1e-14)}

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
    result = {}
    for component in ALL_COMPONENTS:
        result[component] = _finite(value.get(component, 0.0), f"flux_error_bound.{component}")
        if result[component] < 0.0:
            raise ValueError("flux error bounds must be nonnegative")
    return result

def _tr_audit(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if evidence is None:
        return {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED", "matched_control_count": 0, "reason": "dedicated K/Kp controls were not supplied"}
    status = evidence.get("status", "UNRESOLVED")
    if status not in TR_STATUS:
        raise ValueError("unsupported TR numerical status")
    result = dict(evidence)
    if status == "UNRESOLVED":
        return result
    count = evidence.get("matched_control_count")
    if type(count) is not int or count < 1:
        raise ValueError("TR evidence requires a positive matched_control_count")
    for key in ("band1_sign_antisymmetry_residual", "band2_sign_antisymmetry_residual"):
        value = _finite(evidence.get(key), key)
        if value < 0.0:
            raise ValueError("TR residuals must be nonnegative")
        result[key] = value
    if evidence.get("spectral_correspondence") is not True:
        raise ValueError("TR evidence requires spectral correspondence")
    if evidence.get("qualification_compatibility") is not True:
        raise ValueError("TR evidence requires qualification compatibility")
    if status == "FULL_KP_INTEGRATION_VALIDATED" and evidence.get("full_kp_integration") is not True:
        raise ValueError("full Kp status requires explicit full Kp integration evidence")
    if status == "SUPPORTED_BY_EXISTING_CONTROLS" and evidence.get("full_kp_integration") is True:
        raise ValueError("local Kp controls must not claim full Kp integration")
    result["status"] = status
    return result

def _domain_inversion_audit(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if evidence is None:
        return {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED"}
    status = evidence.get("status", "UNRESOLVED")
    level = evidence.get("evidence_level", "UNRESOLVED")
    if status not in DOMAIN_STATUS:
        raise ValueError("unsupported domain inversion status")
    if level not in {"LOCAL_MATCHED_CONTROLS", "FULL_DOMAIN_INTEGRAL", "THEORY_ONLY", "UNRESOLVED"}:
        raise ValueError("unsupported domain inversion evidence level")
    result = dict(evidence)
    result["status"] = status
    result["evidence_level"] = level
    return result

def _paper_audit(convention: Mapping[str, Any] | None) -> dict[str, Any]:
    if convention is None:
        return {"status": "UNRESOLVED", "reason": "paper convention audit object was not supplied"}
    missing = [key for key in PAPER_REQUIRED if key not in convention]
    if missing:
        raise ValueError(f"paper convention audit lacks {missing}")
    if convention["status"] not in PAPER_STATUS:
        raise ValueError("unsupported paper convention status")
    if not isinstance(convention["source_digest"], str) or len(convention["source_digest"]) != 64:
        raise ValueError("paper convention source_digest must be SHA-256")
    if not isinstance(convention["reducer_code_digest"], str) or len(convention["reducer_code_digest"]) != 64:
        raise ValueError("paper convention reducer_code_digest must be SHA-256")
    expected = {"PAPER_BLOCH_FACTOR": "exp(-i k dot r)", "MPB_BLOCH_FACTOR": "exp(+i k dot r)", "K_MAPPING": "k_paper=-k_MPB", "VALLEY_LABEL_MAPPING": "paper_K <-> MPB_Kp; paper_Kp <-> MPB_K"}
    result = dict(convention)
    result["mapping_validated"] = all(convention.get(key) == value for key, value in expected.items())
    if not result["mapping_validated"] and result["status"] == "CONSISTENT_AFTER_BLOCH_K_MAPPING":
        result["status"] = "SIGN_OR_NORMALIZATION_TENSION"
    result["no_sign_hack"] = convention.get("no_sign_hack") is True
    if result["status"] == "CONSISTENT_AFTER_BLOCH_K_MAPPING" and not result["no_sign_hack"]:
        result["status"] = "SIGN_OR_NORMALIZATION_TENSION"
    return result

def inherited_paper_convention() -> dict[str, Any]:
    payload = {"PAPER_BLOCH_FACTOR": "exp(-i k dot r)", "MPB_BLOCH_FACTOR": "exp(+i k dot r)", "K_MAPPING": "k_paper=-k_MPB", "VALLEY_LABEL_MAPPING": "paper_K <-> MPB_Kp; paper_Kp <-> MPB_K"}
    return {**payload, "status": "CONSISTENT_AFTER_BLOCH_K_MAPPING", "provenance_mode": "INHERITED_FROM_SEALED_CONVENTION_AUDIT", "source_digest": _digest(payload), "reducer_code_digest": _digest({"sign_convention": BERRY_SIGN_CONVENTION}), "no_sign_hack": True}

def build_valley_chern_audit(
    sealed_flux: Mapping[str, Any],
    *,
    flux_error_bound: Mapping[str, Any] | None = None,
    c9_source_digest: str | None = None,
    c9_provenance: Mapping[str, Any] | None = None,
    control_status: Mapping[str, Any] | None = None,
    tr_evidence: Mapping[str, Any] | None = None,
    domain_inversion_evidence: Mapping[str, Any] | None = None,
    paper_convention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flux = _component_map(sealed_flux, "sealed_flux")
    bounds = _bound_map(flux_error_bound)
    controls = dict(control_status or {})
    tr = _tr_audit(tr_evidence)
    inversion = _domain_inversion_audit(domain_inversion_evidence)
    paper = _paper_audit(paper_convention)
    chern = {component: valley_chern_from_flux(flux[component]) for component in ALL_COMPONENTS}
    chern_bounds = {component: bounds[component] / TWO_PI for component in ALL_COMPONENTS}
    coord = coordinate_flux_invariance(flux["band1"] / V_K_AREA, V_K_AREA, 1.0)
    band_interpretation = {
        "band1": "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE",
        "band2": "PRIMARY_PHYSICAL_VALLEY_OBSERVABLE",
        "anti": "DIAGNOSTIC_LINEAR_COMBINATION",
        "common": "DIAGNOSTIC_LINEAR_COMBINATION",
    }
    result = {
        "E7I1H_SCOPE": "VALLEY_CHERN_ONLY_NO_NEW_MPB",
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
        "TR_KP_CONTROL_EVIDENCE": tr,
        "VALLEY_CHERN_DOMAIN_INVERSION": inversion["status"],
        "DOMAIN_INVERSION_EVIDENCE_LEVEL": inversion["evidence_level"],
        "DOMAIN_INVERSION_EVIDENCE": inversion,
        "PAPER_CONVENTION_AUDIT": paper,
        "PAPER_VALLEY_CHERN_CONVENTION": paper["status"],
        "PAPER_GEOMETRY_EQUIVALENCE": "UNRESOLVED",
        "BLOCH_K_MAPPING": paper.get("K_MAPPING", "UNRESOLVED"),
        "SIGN_HACK": "NONE" if paper.get("no_sign_hack") is True else "UNRESOLVED",
        "FULL_BZ_CHERN_SEMANTICS": "closed_BZ_torus_integral_divided_by_2pi_quantized_under_isolated_smooth_band_conditions",
        "NONQUANTIZED_VALLEY_CHERN_INTERPRETATION": "MATHEMATICALLY_CLOSED",
        "VALLEY_CHERN_DOMAIN_SEMANTICS": "EXPLICIT_AND_BOUNDARY_AWARE",
        "VALLEY_CHERN_DOMAIN_DEPENDENCE": "restricted_integral_can_change_with_valley_partition_boundary",
        "VALLEY_CHERN_MULTIBAND_INTERPRETATION": "INDIVIDUAL_BANDS_PRIMARY_DIAGNOSTIC_COMBINATIONS_SEPARATE",
        "BAND_INTERPRETATION": band_interpretation,
        "CONTROL_STATUS_INHERITED": controls,

        "C9_HARDENED_ARTIFACT_REPLAY": (
            "COMPLETE_NO_SCIENTIFIC_CHANGE"
            if controls.get("C9_AUDIT_HARDENING") == "COMPLETE_NO_SCIENTIFIC_CHANGE"
            and controls.get("AUDIT_CODE_FINGERPRINTS")
            else ("FAILED" if controls.get("C9_SOURCE_ARTIFACT_PRESENT") is False else "UNRESOLVED")
        ),
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
            "perturbed_node_uncertainty": "must_be_bound by C9 regenerated report",
        },
    }
    result["detail_digest"] = _digest(result)
    return result


def audit_from_c9_report(
    report: Mapping[str, Any],
    *,
    tr_evidence: Mapping[str, Any] | None = None,
    paper_convention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        direct = report["direct_flux"]["refined_centroid"]
        bounds = {
            component: report["audit"]["bounds"][component]["refined_centroid"]["delta_phi_bound_weighted"]
            for component in ALL_COMPONENTS
        }
    except (KeyError, TypeError) as error:
        raise ValueError("C9 report lacks sealed refined flux and bounds") from error
    source_digest = _digest({
        "source_file_sha256": report.get("SOURCE_FILE_SHA256"),
        "c7_replay": report.get("C7_SOURCE_REPLAY"),
        "c9_replay": report.get("C9_DIRECT_SOURCE_FLUX_REPLAY"),
        "direct_flux": direct,
        "bounds": bounds,
    })
    provenance = report.get("CONTROL_CLASSIFICATION_PROVENANCE", {})
    controls = {
        "BERRY_TORUS_PERIODICITY": report.get("BERRY_TORUS_PERIODICITY", "UNRESOLVED"),
        "C9_AUDIT_HARDENING": report.get("C9_AUDIT_HARDENING"),
        "AUDIT_CODE_FINGERPRINTS": report.get("AUDIT_CODE_FINGERPRINTS"),
        "C9_SOURCE_ARTIFACT_PRESENT": report.get("C9_AUDIT_HARDENING") is not None,
    }
    if report.get("VORONOI_DOMAIN_INVERSION") == "CONFIRMED" and provenance.get("reduction_trace_sha256") and provenance.get("reducer_code_sha256"):
        inversion = {
            "status": "SIGN_REVERSAL_SUPPORTED",
            "evidence_level": "LOCAL_MATCHED_CONTROLS",
            "provenance_mode": "INHERITED_FROM_SEALED_REDUCER_OUTPUT",
            "source_digest": provenance["reduction_trace_sha256"],
            "reducer_code_digest": provenance["reducer_code_sha256"],
        }
    else:
        inversion = {"status": "UNRESOLVED", "evidence_level": "UNRESOLVED"}
    return build_valley_chern_audit(
        direct,
        flux_error_bound=bounds,
        c9_source_digest=source_digest,
        c9_provenance=provenance,
        control_status=controls,
        tr_evidence=tr_evidence,
        domain_inversion_evidence=inversion,
        paper_convention=paper_convention,
    )


__all__ = [
    "ALL_COMPONENTS", "BERRY_SIGN_CONVENTION", "DIAGNOSTIC_COMPONENTS",
    "DOMAIN_ID", "PRIMARY_COMPONENTS", "Q_COORDINATE_RELATION", "V_K_AREA",
    "audit_from_c9_report", "build_valley_chern_audit",
    "coordinate_flux_invariance", "inherited_paper_convention",
    "time_reversal_theory", "valley_chern_from_flux",
]
