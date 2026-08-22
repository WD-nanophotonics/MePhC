import meep as mp
import pytest
from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from mephc.valley_benchmark import build_triangular_coordinate_preflight
from mephc.valley_reference_geometry import build_triangular_reference_geometry
from mephc.mpb_reference_adapter import MPB_COORDINATE_PREFLIGHT_PASSED,build_reference_mpb_adapter
def test_triangle_adapter_is_analytic_and_material_bound():
 a=build_reference_mpb_adapter(build_triangular_reference_geometry(0.0),build_triangular_coordinate_preflight())
 assert a.is_ready and a.provenance["primitive"]["construction"]=="mp.Prism" and a.provenance["mpb_geometry_type"]=="Prism"
 assert a.provenance["background_relative_permittivity"]==pytest.approx(2.65) and a.provenance["coordinate_preflight"]["status"]==MPB_COORDINATE_PREFLIGHT_PASSED and a.geometry[0].material==mp.air
def test_circle_adapter_uses_analytic_cylinder():
 g=build_triangular_reference_geometry(0.5);a=build_reference_mpb_adapter(g,build_triangular_coordinate_preflight())
 assert a.provenance["primitive"]["construction"]=="mp.Cylinder" and a.provenance["primitive"]["polygonization_forbidden"] and a.geometry[0].radius==pytest.approx(g.analytic_radius)
def test_provider_settings_are_bound():
 a=build_reference_mpb_adapter(build_triangular_reference_geometry(0.0),build_triangular_coordinate_preflight());p=a.provider(resolution=48)
 assert isinstance(p,MPBLiveEnergySpectralProvider) and (p.resolution,p.num_bands,p.mesh_size)==(48,4,3) and p.deterministic and p.polarization==mp.TE
def test_non_endpoint_is_rejected():
 with pytest.raises(ValueError):build_reference_mpb_adapter(build_triangular_reference_geometry(0.25),build_triangular_coordinate_preflight())
def test_adapter_identity_differs_by_endpoint():
 l=build_reference_mpb_adapter(build_triangular_reference_geometry(0.0),build_triangular_coordinate_preflight());r=build_reference_mpb_adapter(build_triangular_reference_geometry(0.5),build_triangular_coordinate_preflight())
 assert l.provenance["adapter_digest"]!=r.provenance["adapter_digest"]
