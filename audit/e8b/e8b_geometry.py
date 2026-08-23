from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import numpy as np

A0=np.array([[math.sqrt(3.0)/2.0,math.sqrt(3.0)/2.0],[0.5,-0.5]],dtype=float)
G0=np.linalg.inv(A0).T
K_FRACTIONAL=np.array([-1.0/3.0,1.0/3.0])
CENTER_FRACTIONAL=(np.array([1.0/6.0,1.0/6.0]),np.array([-1.0/6.0,-1.0/6.0]))
RADII=(0.15,0.25)
EPSILON_BACKGROUND=1.0
EPSILON_INCLUSION=12.0
WEIGHT_OFFSET=0.05
WEIGHT_SIGMA=0.025
STRAINS=(-0.02,0.0,0.02)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def state(strain):
    s=float(strain)
    F=np.diag([math.exp(s),math.exp(-s)])
    A=F@A0
    G=np.linalg.inv(A).T
    centers0=tuple(A0@c for c in CENTER_FRACTIONAL)
    centers=tuple(F@c for c in centers0)
    axes=tuple((r*math.exp(s),r*math.exp(-s)) for r in RADII)
    K=G@K_FRACTIONAL
    direction=-K/np.linalg.norm(K)
    Q=K+WEIGHT_OFFSET*direction
    cell=abs(float(np.linalg.det(A)))
    ellipse_areas=tuple(math.pi*x*y for x,y in axes)
    payload={"strain":s,"F":F.tolist(),"A":A.tolist(),"G":G.tolist(),"K_fractional":K_FRACTIONAL.tolist(),"K_cart":K.tolist(),"Q_center":Q.tolist(),"centers_fractional":[c.tolist() for c in CENTER_FRACTIONAL],"centers0_cart":[c.tolist() for c in centers0],"centers_cart":[c.tolist() for c in centers],"radii":list(RADII),"ellipse_axes":[[x,y] for x,y in axes],"cell_area":cell,"ellipse_areas":list(ellipse_areas),"fill_fraction":sum(ellipse_areas)/cell,"det_F":float(np.linalg.det(F))}
    payload["geometry_digest"]=digest(payload)
    return payload

def all_states():
    return {str(s):state(s) for s in STRAINS}

def solver_geometry(st):
    import meep as mp
    A=np.asarray(st["A"],dtype=float)
    lattice=mp.Lattice(size=mp.Vector3(1,1),basis1=mp.Vector3(float(A[0,0]),float(A[1,0])),basis2=mp.Vector3(float(A[0,1]),float(A[1,1])))
    geometry=[]
    for center,(ax,ay) in zip(st["centers_cart"],st["ellipse_axes"]):
        geometry.append(mp.Ellipsoid(size=mp.Vector3(2*ax,2*ay,mp.inf),center=mp.Vector3(float(center[0]),float(center[1])),material=mp.Medium(epsilon=EPSILON_INCLUSION)))
    return geometry,lattice

def gh_nodes(order,Q=None):
    if order not in (3,5):
        raise ValueError("only GH3 and GH5 are authorized")
    x,w=np.polynomial.hermite.hermgauss(order)
    center=np.zeros(2) if Q is None else np.asarray(Q,dtype=float)
    rows=[]
    for i in range(order):
        for j in range(order):
            delta=math.sqrt(2.0)*WEIGHT_SIGMA*np.array([x[i],x[j]])
            rows.append({"indices":[i,j],"node":(center+delta).tolist(),"delta":delta.tolist(),"probability":float(w[i]*w[j]/math.pi)})
    return rows

def weight_gradient(delta):
    return np.asarray(delta,dtype=float)/(WEIGHT_SIGMA**2)

def check_geometry():
    states=[state(s) for s in STRAINS]
    assert all(abs(x["det_F"]-1.0)<1e-14 for x in states)
    assert all(abs(x["cell_area"]-states[1]["cell_area"])<1e-14 for x in states)
    base=states[1]["ellipse_areas"]
    assert all(np.allclose(x["ellipse_areas"],base,rtol=0,atol=1e-14) for x in states)
    assert all(abs(x["fill_fraction"]-states[1]["fill_fraction"])<1e-14 for x in states)
    assert np.allclose(states[1]["G"],G0)
    assert all(np.allclose(np.asarray(x["G"]),np.linalg.inv(np.asarray(x["A"])).T,rtol=0,atol=1e-14) for x in states)
    assert all(np.allclose(np.asarray(x["K_cart"]),np.asarray(x["G"])@K_FRACTIONAL,rtol=0,atol=1e-14) for x in states)
    assert abs(sum(x["probability"] for x in gh_nodes(3))-1.0)<1e-14
    return True
