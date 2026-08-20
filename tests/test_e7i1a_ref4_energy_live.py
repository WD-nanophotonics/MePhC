import meep as mp
from meep import mpb
import numpy as np

from mephc.mpb_energy_spectral_provider import MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION, MPBLiveEnergySpectralProvider


def test_live_energy_provider_low_resolution_smoke():
    geometry = [mp.Cylinder(0.2, material=mp.Medium(epsilon=12))]
    lattice = mp.Lattice(size=mp.Vector3(1, 1))
    snapshot = MPBLiveEnergySpectralProvider(
        geometry=geometry,
        geometry_lattice=lattice,
        resolution=6,
        num_bands=2,
        polarization=mp.TE,
        default_material=mp.air,
        deterministic=True,
        mesh_size=3,
        phase_callback=mpb.fix_efield_phase,
    ).solve((0.17, 0.23))
    assert snapshot.provenance["representation"] == "mpb_energy_eh_v1"
    assert snapshot.provenance["caller_provenance"]["live_provider"] == MPB_LIVE_ENERGY_PROVIDER_REPRESENTATION
    assert snapshot.provenance["live_mpb_extraction_validated"] is True
    assert snapshot.e_fields is not None
    assert np.allclose(np.diag(snapshot.gram_matrix), 1.0, atol=1e-12)
