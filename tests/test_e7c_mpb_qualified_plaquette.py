import json
import numpy as np
import pytest
import meep as mp
from mephc.mpb_spectral import adapt_mpb_h_envelopes
from mephc.mpb_spectral_provider import MPBLiveSpectralProvider
from mephc.mpb_qualified_plaquette import qualify_mpb_plaquette
from mephc.spectral_association import SubspaceQualificationThresholds
from mephc.plaquette_domain import PlaquetteRefinementThresholds, PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED

E3=SubspaceQualificationThresholds(.9,.45,.3,.05)
E4C=PlaquetteRefinementThresholds(.9,.45,.3,.1)
def static(k,bands=2):
 f=np.zeros((bands,1,1,3),complex); f[0,0,0,0]=1
 if bands>1:f[1,0,0,1]=1
 if bands>2:f[2,0,0,2]=1
 return adapt_mpb_h_envelopes(k,tuple(range(0,5*bands,5)),f)
def static_levels(bands=2):
 out=[]; sels=[]
 for h in (.02,.01,.005):
  out.append(tuple(static(k,bands) for k in ((.1-h,.2-h),(.1+h,.2-h),(.1+h,.2+h),(.1-h,.2+h),(.1,.2))))
  sels.append(((0,),)*5 if bands==2 else ((0,1),)*5)
 return tuple(out),tuple(sels)
def test_static_rank_one_and_json():
 l,s=static_levels()
 r=qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 assert r.status==PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED and not r.is_live_qualified
 assert "berry" not in json.dumps(r.to_dict()).lower()
def test_static_rank_two():
 l,s=static_levels(3)
 r=qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 assert r.status!="PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED"
def test_invalid_geometry_and_live_guard():
 l,s=static_levels()
 with pytest.raises(ValueError): qualify_mpb_plaquette(l,s,(.02,.02,.005),thresholds=E3,refinement_thresholds=E4C,require_live=False)
 with pytest.raises(ValueError,match="live"): qualify_mpb_plaquette(l,s,(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C)
def test_live_three_level_generic_center():
 lat=mp.Lattice(size=mp.Vector3(1,1)); geo=[mp.Cylinder(.2,material=mp.Medium(epsilon=12))]
 p=MPBLiveSpectralProvider(geometry=geo,geometry_lattice=lat,resolution=6,num_bands=2,polarization=mp.TE,default_material=mp.air,eigensolver_tolerance=1e-7,deterministic=True,mesh_size=3,orthogonality_tolerance=1e-8)
 levels=[]; sels=[]
 for h in (.02,.01,.005):
  pts=((.17-h,.23-h),(.17+h,.23-h),(.17+h,.23+h),(.17-h,.23+h),(.17,.23))
  levels.append(tuple(p.solve(x) for x in pts)); sels.append(((0,),)*5)
 r=qualify_mpb_plaquette(tuple(levels),tuple(sels),(.02,.01,.005),thresholds=E3,refinement_thresholds=E4C)
 assert r.status==PLAQUETTE_REFINEMENT_SINGLE_BAND_QUALIFIED and r.is_live_qualified
