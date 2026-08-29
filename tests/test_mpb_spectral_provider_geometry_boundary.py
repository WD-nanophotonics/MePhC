from __future__ import annotations

from types import SimpleNamespace

import mephc.mpb_spectral_provider as provider_module
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider


def test_build_solver_shallow_copies_geometry_container_at_mpb_boundary(monkeypatch):
    first = object()
    second = object()
    geometry = (first, second)
    lattice = object()
    captured = {}

    class ModeSolver:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    mp = SimpleNamespace(TE=object(), air=object())
    monkeypatch.setattr(
        provider_module,
        "_meep_modules",
        lambda: (mp, SimpleNamespace(ModeSolver=ModeSolver)),
    )
    provider = MPBLiveSpectralProvider(
        geometry=geometry,
        geometry_lattice=lattice,
        resolution=64,
        num_bands=6,
        deterministic=True,
    )

    provider._build_solver(object())

    boundary_geometry = captured["geometry"]
    assert isinstance(boundary_geometry, list)
    assert boundary_geometry is not geometry
    assert boundary_geometry == [first, second]
    assert all(left is right for left, right in zip(boundary_geometry, geometry))
    assert captured["geometry_lattice"] is lattice
