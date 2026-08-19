
"""E7C live MPB bridge into the existing E4A, E4B, and E4C kernels."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any
import numpy as np
from .eigenspace import EigenSubspace
from .mpb_spectral import MPBHEnvelopeSnapshot
from .spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds
from .plaquette_domain import (
    PlaquetteBoundaryQualificationResult, PlaquetteInteriorQualificationResult,
    PlaquetteRefinementLevel, PlaquetteRefinementQualificationResult,
    PlaquetteRefinementThresholds, qualify_plaquette_boundary,
    qualify_plaquette_interior, qualify_plaquette_refinement,
)
E7C_MPB_PLAQUETTE_AUTHORIZATION_SCOPE="mpb_plaquette_domain_only"

def _thaw(v):
    if isinstance(v, Mapping): return {str(k):_thaw(x) for k,x in v.items()}
    if isinstance(v, tuple): return [_thaw(x) for x in v]
    return v
def _freeze(v):
    if isinstance(v, Mapping): return MappingProxyType({str(k):_freeze(x) for k,x in v.items()})
    if isinstance(v,(list,tuple)): return tuple(_freeze(x) for x in v)
    return v
def _safe(v):
    if v is None or type(v) in {bool,str,int}: return v
    if type(v) is float:
        if not np.isfinite(v): raise ValueError("non-finite provenance")
        return v
    if isinstance(v, Mapping): return {str(k):_safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [_safe(x) for x in v]
    raise ValueError("provenance must be JSON-safe")

@dataclass(frozen=True)
class MPBQualifiedPlaquetteResult:
    snapshots: tuple[tuple[MPBHEnvelopeSnapshot,...],...]
    selections: tuple[tuple[tuple[int,...],...],...]
    steps: tuple[float,...]
    boundary_results: tuple[PlaquetteBoundaryQualificationResult,...]
    interior_results: tuple[PlaquetteInteriorQualificationResult,...]
    refinement_result: PlaquetteRefinementQualificationResult
    require_live: bool=True
    authorization_scope: str=E7C_MPB_PLAQUETTE_AUTHORIZATION_SCOPE
    provenance: Mapping[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        if self.authorization_scope != E7C_MPB_PLAQUETTE_AUTHORIZATION_SCOPE: raise ValueError("invalid E7C scope")
        if len(self.snapshots)!=len(self.steps) or len(self.boundary_results)!=len(self.steps) or len(self.interior_results)!=len(self.steps): raise ValueError("level evidence count mismatch")
        if type(self.require_live) is not bool: raise TypeError("require_live must be bool")
        object.__setattr__(self,"snapshots",tuple(tuple(x) for x in self.snapshots))
        object.__setattr__(self,"selections",tuple(tuple(tuple(y) for y in x) for x in self.selections))
        object.__setattr__(self,"steps",tuple(float(x) for x in self.steps))
        object.__setattr__(self,"provenance",_freeze(_safe(dict(self.provenance))))
    @property
    def status(self): return self.refinement_result.status
    @property
    def is_qualified(self): return self.refinement_result.is_qualified
    @property
    def is_live_qualified(self): return self.is_qualified and all(s.provenance.get("live_mpb_extraction_validated") is True for level in self.snapshots for s in level)
    def to_dict(self):
        return {"status":self.status,"is_qualified":self.is_qualified,"is_live_qualified":self.is_live_qualified,"require_live":self.require_live,"authorization_scope":self.authorization_scope,"steps":list(self.steps),"selections":[[list(x) for x in l] for l in self.selections],"boundary_results":[x.to_dict() for x in self.boundary_results],"interior_results":[x.to_dict() for x in self.interior_results],"refinement_result":self.refinement_result.to_dict(),"provenance":_thaw(self.provenance)}

def _sel(s):
    if isinstance(s,(str,bytes)) or not isinstance(s,Sequence) or not s: raise ValueError("selection must be non-empty")
    x=tuple(s)
    if any(isinstance(i,bool) or not isinstance(i,int) or i<0 for i in x) or len(set(x))!=len(x): raise ValueError("invalid local selection")
    return x
def _vertex(s,i,sel):
    if any(j>=s.bands for j in sel): raise ValueError("selection out of range")
    states=[s[j] for j in sel]
    return EigenSubspace(k_point=s.k_point,frame=np.column_stack([x.vector for x in states]),eigenvalues=tuple(x.eigenvalue for x in states),solver_indices=tuple(x.solver_index for x in states),metadata={"source":"E7C MPB plaquette bridge","solver_index_semantics":"ordering metadata only","level":i})
def _ctx(a,sa,b,sb):
    return ExternalIsolationContext(tuple(float(a.frequencies[i]) for i in range(a.bands) if i not in sa),tuple(float(b.frequencies[i]) for i in range(b.bands) if i not in sb),{"source":"E7C excluded snapshot context"})
def qualify_mpb_plaquette(levels, selections, steps, *, thresholds, refinement_thresholds, require_live=True):
    if not isinstance(thresholds,SubspaceQualificationThresholds) or not isinstance(refinement_thresholds,PlaquetteRefinementThresholds): raise TypeError("invalid thresholds")
    if len(levels)<2 or len(levels)!=len(selections) or len(levels)!=len(steps): raise ValueError("E7C requires two or more aligned levels")
    if type(require_live) is not bool: raise TypeError("require_live must be bool")
    normalized=[]; normalized_sel=[]; boundaries=[]; interiors=[]; refinement_levels=[]
    for li,(raw,rawsel,step) in enumerate(zip(levels,selections,steps)):
        if len(raw)!=5 or len(rawsel)!=5: raise ValueError("each level requires four corners and one center")
        sels=tuple(_sel(x) for x in rawsel)
        snaps=tuple(raw)
        if any(not isinstance(x,MPBHEnvelopeSnapshot) for x in snaps): raise TypeError("snapshots required")
        if require_live and any(x.provenance.get("live_mpb_extraction_validated") is not True for x in snaps): raise ValueError("live MPB provenance required")
        if not all(x.is_orthogonality_qualified for x in snaps): raise ValueError("non-qualified snapshot")
        if any(j>=x.bands for x,sel in zip(snaps,sels) for j in sel): raise ValueError("selection out of range")
        vertices=tuple(_vertex(x,li,sel) for x,sel in zip(snaps,sels))
        corners=vertices[:4]; center=vertices[4]
        bctx=tuple(_ctx(snaps[i],sels[i],snaps[(i+1)%4],sels[(i+1)%4]) for i in range(4))
        sctx=tuple(_ctx(snaps[i],sels[i],snaps[4],sels[4]) for i in range(4))
        b=qualify_plaquette_boundary(corners,bctx,thresholds=thresholds,provenance={"source":"E7C MPB bridge"})
        interior=qualify_plaquette_interior(b,center,sctx,provenance={"source":"E7C MPB bridge"})
        normalized.append(snaps); normalized_sel.append(sels); boundaries.append(b); interiors.append(interior); refinement_levels.append(PlaquetteRefinementLevel(b,interior,float(step),{"level":li}))
    refinement=qualify_plaquette_refinement(tuple(refinement_levels),thresholds=refinement_thresholds,provenance={"source":"E7C MPB plaquette bridge","authorization_scope":E7C_MPB_PLAQUETTE_AUTHORIZATION_SCOPE})
    return MPBQualifiedPlaquetteResult(tuple(normalized),tuple(normalized_sel),tuple(float(x) for x in steps),tuple(boundaries),tuple(interiors),refinement,require_live,provenance={"live_required":require_live})
__all__=["E7C_MPB_PLAQUETTE_AUTHORIZATION_SCOPE","MPBQualifiedPlaquetteResult","qualify_mpb_plaquette"]
