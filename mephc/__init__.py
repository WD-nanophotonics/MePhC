"""Generic helpers for building Meep/MPB photonic crystal models."""

__all__ = [
    "Band",
    "BerryCurvatureCalculator",
    "EFSInterpolator",
    "EFSResult",
    "HighSymmetryPath",
    "Lattice",
    "plot_band_path",
    "plot_scalar_field",
    "save_record",
    "load_record",
    "archive_manifest_path",
    "update_archive_manifest",
    "resolve_record",
    "save_record_outputs",
    "preview_pattern",
    "preview_mpb_dielectric",
    "AffineTransform2D",
    "BravaisLattice2D",
    "BrillouinZone2D",
    "first_brillouin_zone",
    "DeformationCapability",
    "DeformationField",
    "ZeroDeformationField",
    "ConstantAffineField",
    "AnalyticDeformationField",
    "SampledDeformationField",
    "PeriodicSupercellField",
    "SupercellLattice",
    "canonicalize_field",
    "field_capabilities",
    "deform_points",
    "deform_pattern_rigid",
    "replicated_lattice_sites",
    "replicated_rigid_pattern",
    "DifferentialMaxwellResponse",
    "SpectralEquivalence",
    "match_equivalent_spectrum",
    "qualify_differential_maxwell_response",
    "GeometryEquivalence",
    "match_geometry",
    "SignEquivalence",
    "DifferentialResolutionLadder",
    "compare_differential_resolution_ladder",
    "verify_periodic_sign_geometry",
    "verify_sign_spectrum",
    "ConvergenceCheck",
    "EigenmodeConvergenceCertificate",
    "EigenmodeConvergenceProvenance",
    "EigenmodeConvergenceThresholds",
    "EigenmodePairEvidence",
    "NumericalConvergenceError",
    "certify_eigenmode_convergence",
    "check_eigenmode_certificate_integrity",
    "revalidate_eigenmode_certificate",
    "EigenmodeCertificateBinding",
    "bind_eigenmode_certificate",
    "EigenmodeCertificateScopeBinding",
    "bind_eigenmode_certificate_for_resolution",
    "GeometryIdentityError",
    "SupercellGeometryIdentity",
    "build_supercell_geometry_identity",
    "identity_from_geometry",
    "EigenmodeQualifiedSupercellBerryCalculator",
    "BerryObservableThresholds",
    "BerryObservableProvenance",
    "QualifiedBerrySample",
    "BerryObservableConvergenceCertificate",
    "certify_berry_observable_convergence",
    "RawEigenstate",
    "EigenSubspace",
    "solve_hermitian",
    "DEFAULT_VALIDATION_TOLERANCE",
    "SubspaceTransportError",
    "SubspaceOverlap",
    "subspace_overlap",
    "SubspaceTransportLink",
    "parallel_transport_link",
    "CLEAR",
    "AMBIGUOUS",
    "INCOMPLETE",
    "SINGLE_BAND_QUALIFIED",
    "SUBSPACE_QUALIFIED",
    "SUBSPACE_NOT_ISOLATED",
    "SUBSPACE_CONTINUITY_UNQUALIFIED",
    "NUMERICALLY_INCOMPLETE",
    "SUBSPACE_REQUIRES_ENLARGEMENT",
    "DISENTANGLEMENT_REQUIRED",
    "RANK_QUALIFIED",
    "RankAdaptiveCandidate",
    "RankAdaptiveSubspaceCandidate",
    "RankAdaptiveAttempt",
    "RankAdaptiveSubspaceResult",
    "RankAdaptiveResult",
    "qualify_rank_adaptive_subspace",
    "evaluate_rank_adaptive_subspace",
    "rank_adaptive_subspace_qualification",
    "PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED",
    "PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED",
    "PLAQUETTE_BOUNDARY_UNQUALIFIED",
    "PLAQUETTE_BOUNDARY_INCOMPLETE",
    "BOUNDARY_AUTHORIZATION_SCOPE",
    "PlaquetteBoundaryQualificationResult",
    "PlaquetteBoundaryResult",
    "qualify_plaquette_boundary",
    "qualify_plaquette",
    "PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED",
    "PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED",
    "PLAQUETTE_SUBSPACE_REQUIRED",
    "PLAQUETTE_BOUNDARY_ONLY",
    "PLAQUETTE_INTERIOR_INCOMPLETE",
    "PLAQUETTE_INTERIOR_UNQUALIFIED",
    "SAMPLED_INTERIOR_AUTHORIZATION_SCOPE",
    "PlaquetteInteriorQualificationResult",
    "PlaquetteInteriorResult",
    "qualify_plaquette_interior",
    "qualify_plaquette_interior_boundary",
    "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED",
    "PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED",
    "PLAQUETTE_REFINEMENT_INCOMPLETE",
    "PLAQUETTE_REFINEMENT_UNQUALIFIED",
    "PLAQUETTE_REFINEMENT_RANK_UNSTABLE",
    "PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED",
    "IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE",
    "PlaquetteRefinementThresholds",
    "PlaquetteRefinementLevel",
    "PlaquetteRefinementMetrics",
    "PlaquetteRefinementQualificationResult",
    "PlaquetteRefinementResult",
    "qualify_plaquette_refinement",
    "qualify_plaquette_identity_refinement",
    "PATH_SINGLE_BAND_QUALIFIED",
    "PATH_SUBSPACE_QUALIFIED",
    "PATH_SUBSPACE_REQUIRED",
    "PATH_UNQUALIFIED",
    "PATH_INCOMPLETE",
    "PATH_AUTHORIZATION_SCOPE",
    "PathQualificationResult",
    "PathResult",
    "qualify_ordered_path",
    "qualify_path",
    "RawAssociationThresholds",
    "RawStateAssociation",
    "associate_raw_states",
    "associate_raw_eigenstates",
    "ExternalIsolationContext",
    "SubspaceQualificationThresholds",
    "SubspaceQualificationResult",
    "qualify_local_subspace",
    "qualify_subspace_pair",
    "WILSON_LINE_QUALIFIED",
    "WILSON_LOOP_QUALIFIED",
    "WILSON_INPUT_INCOMPLETE",
    "WILSON_INPUT_UNQUALIFIED",
    "WILSON_TRANSPORT_AUTHORIZATION_SCOPE",
    "WilsonTransportResult",
    "compose_wilson_transport",
    "compose_wilson_line_or_loop",
    "MPB_H_ENVELOPE_REPRESENTATION",
    "MPB_H_ENVELOPE_QUALIFIED",
    "MPB_H_ENVELOPE_UNQUALIFIED",
    "MPB_H_ORTHOGONAL_QUALIFIED",
    "MPB_H_ORTHOGONAL_UNQUALIFIED",
    "MPBHEnvelopeSnapshot",
    "adapt_mpb_h_envelopes",
    "adapt_mpb_h_envelopes_to_raw_eigenstates",
    "MPB_LIVE_H_PROVIDER_REPRESENTATION",
    "MPBLiveSpectralProvider",
    "solve_mpb_h_spectrum",
    "MPB_PATH_AUTHORIZATION_SCOPE",
    "MPBQualifiedPathInput",
    "MPBQualifiedPathResult",
    "qualify_mpb_spectral_path",
    "qualify_mpb_path",

]


def __getattr__(name):
    if name == "Band":
        from .band import Band

        return Band
    if name == "BerryCurvatureCalculator":
        from .berry import BerryCurvatureCalculator

        return BerryCurvatureCalculator
    if name == "EFSInterpolator":
        from .efs import EFSInterpolator

        return EFSInterpolator
    if name == "EFSResult":
        from .efs import EFSResult

        return EFSResult
    if name == "HighSymmetryPath":
        from .kspace import HighSymmetryPath

        return HighSymmetryPath
    if name == "Lattice":
        from .lattice import Lattice

        return Lattice
    if name == "plot_band_path":
        from .plotting import plot_band_path

        return plot_band_path
    if name == "plot_scalar_field":
        from .plotting import plot_scalar_field

        return plot_scalar_field
    if name == "save_record":
        from .records import save_record

        return save_record
    if name == "load_record":
        from .records import load_record

        return load_record
    if name == "archive_manifest_path":
        from .records import archive_manifest_path

        return archive_manifest_path
    if name == "update_archive_manifest":
        from .records import update_archive_manifest

        return update_archive_manifest
    if name == "resolve_record":
        from .workflows import resolve_record

        return resolve_record
    if name == "save_record_outputs":
        from .workflows import save_record_outputs

        return save_record_outputs
    if name == "preview_pattern":
        from .preview import preview_pattern

        return preview_pattern
    if name == "preview_mpb_dielectric":
        from .preview import preview_mpb_dielectric

        return preview_mpb_dielectric
    if name == "AffineTransform2D":
        from .affine import AffineTransform2D

        return AffineTransform2D
    if name == "BravaisLattice2D":
        from .bravais import BravaisLattice2D

        return BravaisLattice2D
    if name == "BrillouinZone2D":
        from .bz import BrillouinZone2D

        return BrillouinZone2D
    if name == "first_brillouin_zone":
        from .bz import first_brillouin_zone

        return first_brillouin_zone
    if name in {
        "DeformationCapability", "DeformationField", "ZeroDeformationField",
        "ConstantAffineField", "AnalyticDeformationField", "SampledDeformationField",
        "PeriodicSupercellField", "SupercellLattice", "canonicalize_field",
    }:
        from . import deformation

        return getattr(deformation, name)
    if name == "field_capabilities":
        from .capabilities import field_capabilities

        return field_capabilities
    if name in {"deform_points", "deform_pattern_rigid", "replicated_lattice_sites", "replicated_rigid_pattern"}:
        from .deformation_geometry import (
            deform_points,
            deform_pattern_rigid,
            replicated_lattice_sites,
            replicated_rigid_pattern,
        )

        return locals()[name]
    if name in {
        "DifferentialMaxwellResponse", "SpectralEquivalence",
        "match_equivalent_spectrum", "qualify_differential_maxwell_response",
    }:
        from . import r7_response

        return getattr(r7_response, name)
    if name in {"GeometryEquivalence", "match_geometry"}:
        from .geometry_equivalence import GeometryEquivalence, match_geometry

        return {"GeometryEquivalence": GeometryEquivalence, "match_geometry": match_geometry}[name]
    if name in {"SignEquivalence", "DifferentialResolutionLadder", "compare_differential_resolution_ladder", "verify_periodic_sign_geometry", "verify_sign_spectrum"}:
        from . import r7_2_response

        return getattr(r7_2_response, name)
    if name in {
        "ConvergenceCheck", "EigenmodeConvergenceCertificate",
        "EigenmodeConvergenceProvenance", "EigenmodeConvergenceThresholds",
        "EigenmodePairEvidence", "NumericalConvergenceError",
        "certify_eigenmode_convergence",
        "check_eigenmode_certificate_integrity",
        "revalidate_eigenmode_certificate",
    }:
        from . import convergence
        return getattr(convergence, name)
    if name in {
        "CLEAR", "AMBIGUOUS", "INCOMPLETE", "SINGLE_BAND_QUALIFIED",
        "SUBSPACE_QUALIFIED", "SUBSPACE_NOT_ISOLATED",
        "SUBSPACE_CONTINUITY_UNQUALIFIED", "NUMERICALLY_INCOMPLETE",
        "RawAssociationThresholds", "RawStateAssociation", "associate_raw_states",
        "associate_raw_eigenstates", "ExternalIsolationContext",
        "SubspaceQualificationThresholds", "SubspaceQualificationResult",
        "SUBSPACE_REQUIRES_ENLARGEMENT", "DISENTANGLEMENT_REQUIRED", "RANK_QUALIFIED",
        "RankAdaptiveCandidate", "RankAdaptiveSubspaceCandidate", "RankAdaptiveAttempt",
        "RankAdaptiveSubspaceResult", "RankAdaptiveResult",
        "qualify_rank_adaptive_subspace", "evaluate_rank_adaptive_subspace",
        "rank_adaptive_subspace_qualification",
        "PLAQUETTE_BOUNDARY_SINGLE_BAND_QUALIFIED", "PLAQUETTE_BOUNDARY_SUBSPACE_QUALIFIED",
        "PLAQUETTE_BOUNDARY_UNQUALIFIED", "PLAQUETTE_BOUNDARY_INCOMPLETE", "BOUNDARY_AUTHORIZATION_SCOPE",
        "PlaquetteBoundaryQualificationResult", "PlaquetteBoundaryResult",
        "qualify_plaquette_boundary", "qualify_plaquette",
        "PLAQUETTE_INTERIOR_SINGLE_BAND_QUALIFIED", "PLAQUETTE_INTERIOR_SUBSPACE_QUALIFIED",
        "PLAQUETTE_SUBSPACE_REQUIRED", "PLAQUETTE_BOUNDARY_ONLY", "PLAQUETTE_INTERIOR_INCOMPLETE",
        "PLAQUETTE_INTERIOR_UNQUALIFIED", "SAMPLED_INTERIOR_AUTHORIZATION_SCOPE",
        "PlaquetteInteriorQualificationResult", "PlaquetteInteriorResult",
        "qualify_plaquette_interior", "qualify_plaquette_interior_boundary",
        "PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED", "PLAQUETTE_REFINEMENT_SUBSPACE_QUALIFIED",
        "PLAQUETTE_REFINEMENT_INCOMPLETE", "PLAQUETTE_REFINEMENT_UNQUALIFIED",
        "PLAQUETTE_REFINEMENT_RANK_UNSTABLE", "PLAQUETTE_REFINEMENT_SUBSPACE_REQUIRED",
        "IDENTITY_REFINEMENT_AUTHORIZATION_SCOPE", "PlaquetteRefinementThresholds",
        "PlaquetteRefinementLevel", "PlaquetteRefinementMetrics",
        "PlaquetteRefinementQualificationResult", "PlaquetteRefinementResult",
        "qualify_plaquette_refinement", "qualify_plaquette_identity_refinement",
        "PATH_SINGLE_BAND_QUALIFIED", "PATH_SUBSPACE_QUALIFIED", "PATH_SUBSPACE_REQUIRED",
        "PATH_UNQUALIFIED", "PATH_INCOMPLETE", "PATH_AUTHORIZATION_SCOPE",
        "PathQualificationResult", "PathResult", "qualify_ordered_path", "qualify_path",
        "qualify_local_subspace", "qualify_subspace_pair",
    }:
        from . import spectral_association
        return getattr(spectral_association, name)

    if name in {
        "WILSON_LINE_QUALIFIED", "WILSON_LOOP_QUALIFIED",
        "WILSON_INPUT_INCOMPLETE", "WILSON_INPUT_UNQUALIFIED",
        "WILSON_TRANSPORT_AUTHORIZATION_SCOPE", "WilsonTransportResult",
        "compose_wilson_transport", "compose_wilson_line_or_loop",
    }:
        from . import wilson_geometry
        return getattr(wilson_geometry, name)

    if name in {
        "MPB_H_ENVELOPE_REPRESENTATION", "MPB_H_ENVELOPE_QUALIFIED",
        "MPB_H_ENVELOPE_UNQUALIFIED", "MPB_H_ORTHOGONAL_QUALIFIED",
        "MPB_H_ORTHOGONAL_UNQUALIFIED", "MPBHEnvelopeSnapshot",
        "adapt_mpb_h_envelopes", "adapt_mpb_h_envelopes_to_raw_eigenstates",
    }:
        from . import mpb_spectral
        return getattr(mpb_spectral, name)

    if name in {
        "MPB_LIVE_H_PROVIDER_REPRESENTATION", "MPBLiveSpectralProvider",
        "solve_mpb_h_spectrum",
    }:
        from . import mpb_spectral_provider
        return getattr(mpb_spectral_provider, name)

    if name in {
        "MPB_PATH_AUTHORIZATION_SCOPE", "MPBQualifiedPathInput",
        "MPBQualifiedPathResult", "qualify_mpb_spectral_path",
        "qualify_mpb_path",
    }:
        from . import mpb_qualified_path
        return getattr(mpb_qualified_path, name)

    if name in {"EigenmodeCertificateBinding", "bind_eigenmode_certificate", "EigenmodeCertificateScopeBinding", "bind_eigenmode_certificate_for_resolution"}:
        from . import convergence_binding
        return getattr(convergence_binding, name)
    if name in {"GeometryIdentityError", "SupercellGeometryIdentity", "build_supercell_geometry_identity", "identity_from_geometry"}:
        from . import geometry_identity
        return getattr(geometry_identity, name)
    if name == "EigenmodeQualifiedSupercellBerryCalculator":
        from .qualified_berry import EigenmodeQualifiedSupercellBerryCalculator
        return EigenmodeQualifiedSupercellBerryCalculator
    if name in {
        "BerryObservableThresholds", "BerryObservableProvenance",
        "QualifiedBerrySample", "BerryObservableConvergenceCertificate",
        "certify_berry_observable_convergence",
    }:
        from . import berry_convergence
        return getattr(berry_convergence, name)
    if name in {"RawEigenstate", "EigenSubspace"}:
        from .eigenspace import RawEigenstate, EigenSubspace
        return {"RawEigenstate": RawEigenstate, "EigenSubspace": EigenSubspace}[name]
    if name == "solve_hermitian":
        from .toy_eigensolver import solve_hermitian
        return solve_hermitian
    if name in {"DEFAULT_VALIDATION_TOLERANCE", "SubspaceTransportError", "SubspaceOverlap", "subspace_overlap", "SubspaceTransportLink", "parallel_transport_link"}:
        from . import subspace_transport
        return getattr(subspace_transport, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
