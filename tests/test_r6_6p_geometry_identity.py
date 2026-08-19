import json
import hashlib
from unittest.mock import patch

import meep as mp
import numpy as np
import pytest

from mephc.band import Band
from mephc.bravais import BravaisLattice2D
from mephc.convergence import (
    EigenmodeConvergenceProvenance,
    EigenmodePairEvidence,
    certify_eigenmode_convergence,
)
from mephc.convergence_binding import bind_eigenmode_certificate
from mephc.deformation import ZeroDeformationField
from mephc.geometry_identity import (
    GeometryIdentityError,
    SupercellGeometryIdentity,
    build_supercell_geometry_identity,
)
from mephc.response import R6_AMPLITUDES, benchmark_field


def lattice(size=(2, 2, 0)):
    return mp.Lattice(size=mp.Vector3(*size))


def geometry(*, material=mp.air, center=(0.2, 0.3, 0.0), order="block-prism-cylinder"):
    block = mp.Block(
        center=mp.Vector3(0, 0, 0),
        size=mp.Vector3(1, 1, 1),
        material=material,
    )
    prism = mp.Prism(
        [mp.Vector3(0, 0), mp.Vector3(0.2, 0), mp.Vector3(0, 0.2)],
        height=1,
        material=material,
    )
    cylinder = mp.Cylinder(
        center=mp.Vector3(*center), radius=0.1, height=1, material=material
    )
    values = {"block": block, "prism": prism, "cylinder": cylinder}
    return [values[name] for name in order.split("-")]


def identity(*, objects=None, replication=(2, 2), geometry_lattice=None, material=mp.air):
    return build_supercell_geometry_identity(
        geometry_lattice=geometry_lattice or lattice(),
        geometry=geometry if objects is None else objects,
        replication=replication,
        default_material=mp.air,
    )


def active_pattern():
    return [np.array([[0.1, 0.1], [0.2, 0.1], [0.1, 0.2]], dtype=float)]


def active_field():
    return benchmark_field(BravaisLattice2D.square(), R6_AMPLITUDES[0])


def certificate_provenance(digest):
    return EigenmodeConvergenceProvenance(
        backend="mpb",
        geometry_digest=digest,
        target_band=0,
        num_bands=2,
        polarization="TE",
        deterministic=True,
        eigensolver_tolerance=1e-11,
        mesh_size=3,
        field_representation="periodic_h_bloch_envelope",
    )


def test_repeated_construction_and_resolution_independence():
    first = identity(objects=geometry(order="block-prism-cylinder"))
    second = identity(objects=geometry(order="block-prism-cylinder"))
    assert first.payload == second.payload
    assert first.digest == second.digest
    assert first.schema == "mephc-supercell-geometry/v1"
    assert len(first.digest) == 64 and first.digest == first.digest.lower()
    band4 = Band(resolution=4, lattice_type="square")
    band9 = Band(resolution=9, lattice_type="square")
    assert band4.build_supercell_geometry_identity(active_pattern(), active_field()).digest == band9.build_supercell_geometry_identity(active_pattern(), active_field()).digest


def test_shared_context_is_the_public_identity_authority():
    band = Band(resolution=4, lattice_type="square")
    field = active_field()
    pattern = active_pattern()
    context = band._prepare_supercell_geometry(pattern, field)
    assert isinstance(context.identity, SupercellGeometryIdentity)
    with patch.object(band, "_prepare_supercell_geometry", return_value=context) as prepare:
        actual = band.build_supercell_geometry_identity(pattern, field)
    prepare.assert_called_once_with(pattern, field)
    assert actual is context.identity


def test_identity_changes_for_geometry_replication_material_and_order():
    baseline = identity(objects=geometry())
    moved = identity(objects=geometry(center=(0.25, 0.3, 0.0)))
    changed_vertex = geometry()
    changed_vertex[1] = mp.Prism(
        [mp.Vector3(0, 0), mp.Vector3(0.25, 0), mp.Vector3(0, 0.2)],
        height=1,
        material=mp.air,
    )
    material_changed = mp.Medium(epsilon=4.0)
    changed_material = identity(objects=geometry(material=material_changed))
    reordered = identity(objects=geometry(order="cylinder-prism-block"))
    changed_replication = identity(objects=geometry(), replication=(3, 2))
    changed_lattice = identity(objects=geometry(), geometry_lattice=lattice((3, 2, 0)))
    assert baseline.digest != moved.digest
    assert baseline.digest != identity(objects=changed_vertex).digest
    assert baseline.digest != changed_material.digest
    assert baseline.digest != reordered.digest
    assert baseline.digest != changed_replication.digest
    assert baseline.digest != changed_lattice.digest


def test_unsupported_geometry_and_material_fail_closed():
    class Unsupported:
        pass

    with pytest.raises(ValueError, match="unsupported geometry type"):
        identity(objects=[Unsupported()])
    anisotropic = mp.Medium(epsilon_diag=mp.Vector3(2, 3, 2))
    with pytest.raises(ValueError, match="scalar isotropic"):
        identity(objects=geometry(material=anisotropic), material=anisotropic)


def test_json_determinism_and_canonical_digest():
    result = identity(objects=geometry())
    serialized = result.to_dict()
    assert json.loads(json.dumps(serialized, sort_keys=True)) == serialized
    payload_json = json.dumps(result.payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert hashlib.sha256(payload_json.encode("utf-8")).hexdigest() == result.digest
    assert serialized["payload"]["schema"] == "mephc-supercell-geometry/v1"
    assert "resolution" not in payload_json
    assert "eigensolver_tolerance" not in payload_json


def test_active_path_smoke_and_convergence_binding_bridge():
    band = Band(resolution=4, lattice_type="square")
    context = band._prepare_supercell_geometry(active_pattern(), active_field())
    assert context.identity.payload["schema"] == "mephc-supercell-geometry/v1"
    assert context.identity.payload["replication"] == [2, 2]
    assert len(context.identity.payload["objects"]) == 2
    assert [item["type"] for item in context.identity.payload["objects"]] == ["mp.Block", "mp.Prism"]
    assert context.identity.payload["geometry_lattice"]["size"][:2] == [2.0, 2.0]
    provenance = certificate_provenance(context.identity.digest)
    certificate = certify_eigenmode_convergence([
        EigenmodePairEvidence(64, 80, 1e-8, 0.999999, 1e-4, 0.26),
        EigenmodePairEvidence(80, 96, 1e-8, 0.999999, 1e-4, 0.26),
    ], provenance=provenance)
    binding = bind_eigenmode_certificate(certificate, expected_provenance=provenance)
    assert binding.status == "PASS"


def test_identity_payload_records_periodicity_semantics():
    result = identity(objects=geometry())
    assert result.payload["periodicity_semantics"]["ensure_periodicity"] is True
    assert result.payload["periodicity_semantics"]["authority"] == "Band._prepare_supercell_geometry"
