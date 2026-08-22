"""Bounded E7I.2C adapter for the audited triangular reference endpoints."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json
from collections.abc import Sequence
from typing import Any
import numpy as np
from .mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider
from .valley_benchmark import ReferenceCoordinatePreflight
from .valley_reference_geometry import TriangularReferenceGeometry
ADAPTER_VERSION="e7i2c_reference_mpb_adapter_v1"; REFERENCE_POLARIZATION="TE"; AIR_EPSILON=1.0
MPB_COORDINATE_PREFLIGHT_PASSED="PASSED"; MPB_COORDINATE_PREFLIGHT_FAILED="FAILED"
def _digest(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def _vec(mp,p):return mp.Vector3(float(p[0]),float(p[1]),0.0)
def _lattice(mp,p):
 b=np.asarray(p.real_space_basis,dtype=float)
 return mp.Lattice(size=mp.Vector3(1,1,0),basis1=mp.Vector3(float(b[0,0]),float(b[1,0]),0),basis2=mp.Vector3(float(b[0,1]),float(b[1,1]),0))
@dataclass(frozen=True,slots=True)
class MPBReferenceAdapter:
 reference_geometry:TriangularReferenceGeometry; coordinate_preflight:ReferenceCoordinatePreflight; geometry:tuple[Any,...]; geometry_lattice:Any; background_material:Any; inclusion_material:Any; polarization:Any; provenance:dict[str,Any]; coordinate_preflight_status:str=MPB_COORDINATE_PREFLIGHT_PASSED
 def __post_init__(self):
  if self.coordinate_preflight_status not in {MPB_COORDINATE_PREFLIGHT_PASSED,MPB_COORDINATE_PREFLIGHT_FAILED}:raise ValueError("invalid coordinate preflight status")
 @property
 def is_ready(self):return self.coordinate_preflight_status==MPB_COORDINATE_PREFLIGHT_PASSED
 def provider(self,*,resolution,num_bands=4,eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3):
  if not self.is_ready:raise RuntimeError("MPB coordinate preflight did not pass")
  return MPBLiveEnergySpectralProvider(geometry=list(self.geometry),geometry_lattice=self.geometry_lattice,resolution=resolution,num_bands=num_bands,polarization=self.polarization,default_material=self.background_material,eigensolver_tolerance=eigensolver_tolerance,deterministic=deterministic,mesh_size=mesh_size)
 def to_dict(self):return dict(self.provenance)
def build_reference_mpb_adapter(g:TriangularReferenceGeometry,p:ReferenceCoordinatePreflight)->MPBReferenceAdapter:
 if not isinstance(g,TriangularReferenceGeometry) or not isinstance(p,ReferenceCoordinatePreflight):raise TypeError("invalid reference contract")
 if g.primitive_kind not in {"triangle","circle"}:raise ValueError("only exact endpoints are authorized")
 if g.geometry_equivalence!="PAPER_PARAMETER_BOUND" or g.paper_parameter_equivalence!="PAPER_PARAMETER_BOUND":raise ValueError("reference parameter equivalence unresolved")
 if g.polarization!=REFERENCE_POLARIZATION:raise ValueError("reference polarization must be TE")
 eps=g.mpb_epsilon_value
 if eps is None or g.material_contract_status!="REFERENCE_BOUND":raise ValueError("reference material contract is not bound")
 if not p.ready:raise ValueError("solver-neutral coordinate preflight did not pass")
 import meep as mp
 lat=_lattice(mp,p); bg,inc=mp.Medium(epsilon=float(eps)),mp.air
 if g.primitive_kind=="triangle":
  geo=(mp.Prism(vertices=[_vec(mp,x) for x in g.vertices],height=mp.inf,material=inc),); prim={"kind":"triangle","construction":"mp.Prism","vertex_count":len(g.vertices),"analytic_radius":g.analytic_radius}
 else:
  if g.analytic_radius is None:raise ValueError("circle endpoint requires analytic radius")
  geo=(mp.Cylinder(radius=float(g.analytic_radius),height=mp.inf,material=inc),); prim={"kind":"circle","construction":"mp.Cylinder","analytic_radius":float(g.analytic_radius),"polygonization_forbidden":True}
 def frac(q):
  x=mp.cartesian_to_reciprocal(_vec(mp,q),lat);return tuple(float(getattr(x,k)) for k in ("x","y"))
 q=(0.173,0.231); ak,ek=frac(p.public_k),p.public_q_to_mpb(p.public_k); ao,eo=frac(q),p.public_q_to_mpb(q)
 res={"K":float(np.linalg.norm(np.asarray(ak)-ek)),"off_axis":float(np.linalg.norm(np.asarray(ao)-eo))}
 status=MPB_COORDINATE_PREFLIGHT_PASSED if max(res.values())<=p.tolerance else MPB_COORDINATE_PREFLIGHT_FAILED
 prov={"schema":"e7i2c_mpb_reference_adapter_v1","adapter_version":ADAPTER_VERSION,"geometry_digest":g.geometry_digest,"material_digest":g.material_contract_digest,"mapping_digest":p.mapping_digest,"primitive":prim,"mpb_geometry_type":type(geo[0]).__name__,"background_relative_permittivity":float(eps),"inclusion_epsilon":AIR_EPSILON,"polarization":REFERENCE_POLARIZATION,"lattice_basis":[[float(p.real_space_basis[0][0]),float(p.real_space_basis[1][0])],[float(p.real_space_basis[0][1]),float(p.real_space_basis[1][1])]],"coordinate_preflight":{"status":status,"public_K":list(p.public_k),"expected_fractional_K":list(ek),"actual_fractional_K":list(ak),"off_axis_public_q":list(q),"expected_fractional_off_axis":list(eo),"actual_fractional_off_axis":list(ao),"residuals":res},"provider_representation":"mpb_live_energy_eh_v1"}
 prov["adapter_digest"]=_digest(prov)
 return MPBReferenceAdapter(g,p,geo,lat,bg,inc,mp.TE,prov,status)
__all__=["ADAPTER_VERSION","AIR_EPSILON","MPB_COORDINATE_PREFLIGHT_FAILED","MPB_COORDINATE_PREFLIGHT_PASSED","MPBReferenceAdapter","REFERENCE_POLARIZATION","build_reference_mpb_adapter"]
