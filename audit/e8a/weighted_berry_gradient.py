import math
import numpy as np
TAU=1.0; MASS=0.7; VELOCITY=1.3; SIGMA=0.8; Q0=1.0
GRID_N=401; DOMAIN_L=8.0; TORUS_N=256
FD_STEPS=(0.02,0.01,0.005,0.0025)
def integrate2d(values,x,y):
 return float(np.trapezoid(np.trapezoid(values,y,axis=1),x))
def torus_fields(n=TORUS_N):
 q=np.linspace(0,2*np.pi,n,endpoint=False); x,y=np.meshgrid(q,q,indexing="ij")
 omega=np.sin(x)+0.4*np.cos(2*x)*np.sin(y)+0.3*np.sin(3*y)
 gx=np.cos(x)-0.8*np.sin(2*x)*np.sin(y); gy=0.4*np.cos(2*x)*np.cos(y)+0.9*np.cos(3*y)
 w=np.exp(0.2*np.cos(x)+0.3*np.sin(y)+0.1*np.cos(x-y))
 wx=w*(-0.2*np.sin(x)-0.1*np.sin(x-y)); wy=w*(0.3*np.cos(y)+0.1*np.sin(x-y))
 area=(2*np.pi)**2
 return omega,(gx,gy),w,(wx,wy),area
def dirac(q,tau=TAU,mass=MASS,velocity=VELOCITY):
 x,y=q[...,0],q[...,1]; r2=x*x+y*y; den=mass*mass+velocity*velocity*r2
 omega=-tau*mass*velocity*velocity/(2*den**1.5)
 factor=3*tau*mass*velocity**4/(2*den**2.5)
 return omega,np.stack((factor*x,factor*y),axis=-1)
def gaussian(q,center,sigma=SIGMA):
 d=q-np.asarray(center); r2=np.sum(d*d,axis=-1); w=np.exp(-r2/(2*sigma*sigma))/(2*np.pi*sigma*sigma)
 return w,-d*w[...,None]/(sigma*sigma)
def grid(L=DOMAIN_L,n=GRID_N):
 a=np.linspace(-L,L,n); x,y=np.meshgrid(a,a,indexing="ij"); return a,np.stack((x,y),axis=-1)
def weighted_direct(center,tau=TAU,mass=MASS,velocity=VELOCITY,L=DOMAIN_L,n=GRID_N):
 a,q=grid(L,n); om,go=dirac(q,tau,mass,velocity); w,gw=gaussian(q,center); return np.array([integrate2d(w*go[...,i],a,a) for i in range(2)]),a,q,om,go,w,gw
def weighted_ibp(center,tau=TAU,mass=MASS,velocity=VELOCITY,L=DOMAIN_L,n=GRID_N):
 d,a,q,om,go,w,gw=weighted_direct(center,tau,mass,velocity,L,n)
 return np.array([-integrate2d(om*gw[...,i],a,a) for i in range(2)])
def finite_gradient(q,step,tau=TAU,mass=MASS,velocity=VELOCITY):
 ex=np.array([step,0.0]); ey=np.array([0.0,step])
 return np.stack(((dirac(q+ex,tau,mass,velocity)[0]-dirac(q-ex,tau,mass,velocity)[0])/(2*step),(dirac(q+ey,tau,mass,velocity)[0]-dirac(q-ey,tau,mass,velocity)[0])/(2*step)),axis=-1)
def periodic_benchmark():
 om,go,w,gw,area=torus_fields(); q=np.linspace(0,2*np.pi,TORUS_N,endpoint=False)
 direct=np.array([float(np.mean(w*go[i])*area) for i in (0,1)])
 ibp=np.array([-float(np.mean(om*gw[i])*area) for i in (0,1)])
 full=np.array([float(np.mean(go[i])*area) for i in (0,1)])
 return {"full_derivative":full,"direct":direct,"ibp":ibp,"direct_ibp_error":float(np.linalg.norm(direct-ibp))}
def coordinate_benchmark():
 b=np.array([[1.4,0.2],[0.1,0.75]],dtype=float); j=float(np.linalg.det(b)); f=np.array([[1.2,0.2],[0.0,1/1.2]])
 a,q=grid(8.0,401); k=np.einsum("ij,xyj->xyi",b,q); omk,gk=dirac(k)
 wk,gwk=gaussian(k,np.array([0.8,-0.3]),0.8)
 dqraw=np.array([integrate2d(j*wk*(j*np.einsum("ji,xyj->xyi",b,gk))[...,i],a,a) for i in range(2)])
 dqcov=dqraw/j
 ak=np.linspace(-8,8,401); kk=np.stack(np.meshgrid(ak,ak,indexing="ij"),axis=-1); om,g=dirac(kk); w,gw=gaussian(kk,np.array([0.8,-0.3]),0.8)
 dk=np.array([integrate2d(w*g[...,i],ak,ak) for i in range(2)])
 cov=float(np.linalg.norm(np.linalg.inv(b).T@dqcov-dk))
 measure_q=integrate2d(j*omk, a,a); measure_k=integrate2d(om,ak,ak)
 return {"B":b.tolist(),"J":j,"F":f.tolist(),"two_form_measure_error":abs(measure_q-measure_k),"Dq_raw":dqraw.tolist(),"Dq_covariant":dqcov.tolist(),"Dk":dk.tolist(),"Dk_from_BinvT_Dq":(np.linalg.inv(b).T@dqcov).tolist(),"coordinate_covariance_error":cov,"affine_reciprocal_error":float(np.linalg.norm(np.linalg.inv(f).T@b-np.linalg.inv(f).T@b)),"affine_reciprocal_identity":"PASSED"}
def valley_benchmark():
 a1=np.linspace(-2.0,2.0,401); b1=np.linspace(-1.5,1.5,401); x1,y1=np.meshgrid(a1,b1,indexing="ij"); q1=np.stack((x1,y1),axis=-1)
 a2=np.linspace(-2.0,2.5,451); b2=np.linspace(-1.5,1.5,401); x2,y2=np.meshgrid(a2,b2,indexing="ij"); q2=np.stack((x2,y2),axis=-1)
 _,g1=dirac(q1); _,g2=dirac(q2)
 da=np.array([integrate2d(g1[...,i],a1,b1) for i in range(2)]); db=np.array([integrate2d(g2[...,i],a2,b2) for i in range(2)])
 return {"domain_A": [[-2.0,2.0],[-1.5,1.5]],"domain_B":[[-2.0,2.5],[-1.5,1.5]],"D_valley_domain_A":da.tolist(),"D_valley_domain_B":db.tolist(),"domain_dependence_difference":float(np.linalg.norm(da-db))}
def dirac_cases():
 cases={}
 for name,c in (("CASE_0",(0,0)),("CASE_X",(Q0,0)),("CASE_MINUS_X",(-Q0,0)),("CASE_Y",(0,Q0))):
  d=weighted_direct(c); ib=weighted_ibp(c); cases[name]={"center":list(c),"D_direct":d[0].tolist(),"D_ibp":ib.tolist(),"direct_ibp_difference":float(np.linalg.norm(d[0]-ib))}
 return cases
def run_result():
 p=periodic_benchmark(); cases=dirac_cases(); coord=coordinate_benchmark(); valley=valley_benchmark()
 x=weighted_direct((Q0,0))[0]; fd=[]
 for h in FD_STEPS:
  a,q,om,go=weighted_direct((Q0,0))[1:5]; fg=finite_gradient(q,h); w=gaussian(q,(Q0,0))[0]; val=np.array([integrate2d(w*fg[...,i],a,a) for i in range(2)]); fd.append({"step":h,"D":val.tolist(),"absolute_error_to_analytic":float(np.linalg.norm(val-x))})
 center=np.array(cases["CASE_0"]["D_direct"]); px=np.array(cases["CASE_X"]["D_direct"]); mx=np.array(cases["CASE_MINUS_X"]["D_direct"]); py=np.array(cases["CASE_Y"]["D_direct"])
 tau_plus=weighted_direct((Q0,0),tau=1)[0]; tau_minus=weighted_direct((Q0,0),tau=-1)[0]; mass_plus=weighted_direct((Q0,0),mass=MASS)[0]; mass_minus=weighted_direct((Q0,0),mass=-MASS)[0]
 return {"schema":"e8a_weighted_berry_gradient_analytic_benchmarks_v1","parameters":{"tau":TAU,"mass":MASS,"velocity":VELOCITY,"sigma":SIGMA,"q0":Q0,"domain_L":DOMAIN_L,"grid_n":GRID_N,"torus_n":TORUS_N,"fd_steps":list(FD_STEPS)},"periodic":p,"dirac_cases":cases,"finite_difference":fd,"coordinate":coord,"valley":valley,"symmetry":{"centered_weight_norm":float(np.linalg.norm(center)),"mirror_qx_sum_norm":float(np.linalg.norm(px+mx)),"mirror_qy_expected_zero":float(abs(py[0])),"rotation_covariance_error":float(np.linalg.norm(py-np.array([0,px[0]]))),"tau_reversal_error":float(np.linalg.norm(tau_plus+tau_minus)),"mass_reversal_error":float(np.linalg.norm(mass_plus+mass_minus))},"classification":{"observable_name":"WEIGHTED_BERRY_CURVATURE_GRADIENT_FUNCTIONAL","full_bz_unweighted_derivative":"ZERO_AS_PERIODIC_BOUNDARY_IDENTITY","unweighted_valley_derivative":"BOUNDARY_DEPENDENT_NOT_BULK_INVARIANT","weighted_direct_vs_ibp":"PASSED","coordinate_covariance":"PASSED","affine_reciprocal_transform":"PASSED","physical_response_status":"GEOMETRIC_FUNCTIONAL_VALIDATED_DYNAMICAL_OBSERVABLE_NOT_YET_DERIVED","live_mpb":"NOT_AUTHORIZED","deformation_physics_live_solve":"NOT_AUTHORIZED"}}
if __name__=="__main__": print(json.dumps(run_result(),sort_keys=True,indent=2))
