import math

import meep as mp
from meep import mpb
import numpy as np

from mephc.mpb_energy_spectral_provider import (
    MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION,
    MPBLiveEnergySpectralProvider,
)


def _lattice():
    root3_over_two = math.sqrt(3.0) / 2.0
    return mp.Lattice(size=mp.Vector3(1, 1), basis1=mp.Vector3(root3_over_two, 0.5), basis2=mp.Vector3(root3_over_two, -0.5))


def _plaquette(center, h):
    x, y = center
    half = h / 2.0
    return ((x-half, y-half), (x+half, y-half), (x+half, y+half), (x-half, y+half))


def _anti_and_gap(center):
    provider = MPBLiveEnergySpectralProvider(
        geometry=[
            mp.Cylinder(center=mp.Vector3(1/6, 1/6), radius=.15, material=mp.Medium(epsilon=12.0)),
            mp.Cylinder(center=mp.Vector3(-1/6, -1/6), radius=.25, material=mp.Medium(epsilon=12.0)),
        ], geometry_lattice=_lattice(), resolution=64, num_bands=6, polarization=mp.TM,
        default_material=mp.air, eigensolver_tolerance=1e-7, deterministic=True,
        mesh_size=3, phase_callback=mpb.fix_efield_phase,
    )
    h=.001
    snapshots=tuple(provider.solve(point) for point in _plaquette(center,h))
    assert all(s.provenance['representation']=='mpb_energy_eh_v1' for s in snapshots)
    assert all(s.provenance['caller_provenance']['live_provider']==MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION for s in snapshots)
    phases=[]
    for band in (0,1):
        links=[]
        for i in range(4):
            z=np.vdot(snapshots[i].normalized_vectors[band],snapshots[(i+1)%4].normalized_vectors[band])
            assert abs(z)>.9
            links.append(z/abs(z))
        phases.append(float(np.angle(np.prod(links))))
    omega_q=[-phase/(h*h) for phase in phases]
    omega_phys=[x/(2*math.pi)**2 for x in omega_q]
    anti_q=(omega_q[0]-omega_q[1])/2
    anti_phys=(omega_phys[0]-omega_phys[1])/2
    assert all(s.frequencies[2]-s.frequencies[1]>.05 for s in snapshots)
    assert anti_q*anti_phys>0
    np.testing.assert_allclose(anti_phys,anti_q/(2*math.pi)**2,rtol=1e-12,atol=1e-15)
    return anti_q


def test_m1_true_d0500_centered_energy_eh_k_kprime_normalization_regression():
    k_anti=_anti_and_gap((0.0,-2.0/3.0))
    k_prime_anti=_anti_and_gap((0.0,2.0/3.0))
    assert k_anti*k_prime_anti<0
    assert abs(abs(k_anti)-abs(k_prime_anti))/abs(k_anti)<.02
