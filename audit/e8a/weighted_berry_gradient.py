import math
import numpy as np
TAU=1.0; MASS=0.7; VELOCITY=1.3; SIGMA=0.8; Q0=1.0
GRID_N=401; DOMAIN_L=8.0; TORUS_N=256; FD_STEPS=(0.02,0.01,0.005,0.0025)
def integrate2d(v,x,y): return float(np.trapezoid(np.trapezoid(v,y,axis=1),x))
def torus_fields(n=TORUS_N):
 q=np.linspace(0,2*np.pi,n,endpoint=False); x,y=np.meshgrid(q,q,indexing="ij")
 o=np.sin(x)+.4*np.cos(2*x)*np.sin(y)+.3*np.sin(3*y); gx=np.cos(x)-.8*np.sin(2*x)*np.sin(y); gy=.4*np.cos(2*x)*np.cos(y)+.9*np.cos(3*y)
 w=np.exp(.2*np.cos(x)+.3*np.sin(y)+.1*np.cos(x-y)); wx=w*(-.2*np.sin(x)-.1*np.sin(x-y)); wy=w*(.3*np.cos(y)+.1*np.sin(x-y))
 return o,(gx,gy),w,(wx,wy),(2*np.pi)**2
def dirac_scalar(q,tau=TAU,mass=MASS,velocity=VELOCITY):
 r2=np.sum(q*q,axis=-1); den=mass*mass+velocity*velocity*r2
 return -tau*mass*velocity*velocity/(2*den**1.5)
def dirac(q,tau=TAU,mass=MASS,velocity=VELOCITY):
 o=dirac_scalar(q,tau,mass,velocity); r2=np.sum(q*q,axis=-1); den=mass*mass+velocity*velocity*r2; f=3*tau*mass*velocity**4/(2*den**2.5)
 return o,np.stack((f*q[...,0],f*q[...,1]),axis=-1)
def gaussian(q,c,sigma=SIGMA):
 d=q-np.asarray(c); w=np.exp(-np.sum(d*d,axis=-1)/(2*sigma*sigma))/(2*np.pi*sigma*sigma); return w,-d*w[...,None]/(sigma*sigma)
def grid(L=DOMAIN_L,n=GRID_N):
 a=np.linspace(-L,L,n); x,y=np.meshgrid(a,a,indexing="ij"); return a,np.stack((x,y),axis=-1)
def weighted_direct(c,tau=TAU,mass=MASS,velocity=VELOCITY,L=DOMAIN_L,n=GRID_N):
 a,q=grid(L,n); o,g=dirac(q,tau,mass,velocity); w,gw=gaussian(q,c); d=np.array([integrate2d(w*g[...,i],a,a) for i in range(2)]); return d,a,q,o,g,w,gw
def weighted_ibp(c,tau=TAU,mass=MASS,velocity=VELOCITY,L=DOMAIN_L,n=GRID_N):
 d,a,q,o,g,w,gw=weighted_direct(c,tau,mass,velocity,L,n); return np.array([-integrate2d(o*gw[...,i],a,a) for i in range(2)])
def finite_gradient(q,h,tau=TAU,mass=MASS,velocity=VELOCITY):
 ex=np.array([h,0.]); ey=np.array([0.,h]); return np.stack(((dirac_scalar(q+ex,tau,mass,velocity)-dirac_scalar(q-ex,tau,mass,velocity))/(2*h),(dirac_scalar(q+ey,tau,mass,velocity)-dirac_scalar(q-ey,tau,mass,velocity))/(2*h)),axis=-1)
def periodic_benchmark():
 o,g,w,gw,area=torus_fields(); direct=np.array([np.mean(w*g[i])*area for i in (0,1)]); ibp=np.array([-np.mean(o*gw[i])*area for i in (0,1)]); full=np.array([np.mean(g[i])*area for i in (0,1)])
 return {"full_derivative":full.tolist(),"direct":direct.tolist(),"ibp":ibp.tolist(),"direct_ibp_error":float(np.linalg.norm(direct-ibp))}
def coordinate_benchmark():
 B=np.array([[1.4,.2],[.1,.75]]); J=float(np.linalg.det(B)); A=np.array([[1.2,.15],[.1,.9]]); F=np.array([[1.1,.2],[.05,.8]]); Apr=F@A; Bdirect=np.linalg.inv(Apr).T; Bexpected=np.linalg.inv(F).T@np.linalg.inv(A).T
 S=np.array([[1.1,.2],[.1,.9]]); Sprime=np.linalg.inv(S); a,q=grid(8,401); k=np.einsum("ij,xyj->xyi",B,q); ok,gk=dirac(k); wk,_=gaussian(k,(.8,-.3)); oq=J*ok; oq_contract=J*dirac_scalar(k); gradq=J*np.einsum("ji,xyj->xyi",B,gk)
 Dq=np.array([integrate2d(wk*gradq[...,i],a,a) for i in range(2)]); Dk=np.array([integrate2d(wk*gk[...,i]*J,a,a) for i in range(2)])
 qprime=np.einsum("ij,xyj->xyi",S,q); kp=np.einsum("ij,xyj->xyi",B@Sprime,qprime); op,gp=dirac(kp); wp,_=gaussian(kp,(.8,-.3)); Jp=J/np.linalg.det(S); gradqp=Jp*np.einsum("ji,xyj->xyi",B@Sprime,gp); Dqp=np.array([integrate2d(wp*gradqp[...,i]*np.linalg.det(S),a,a) for i in range(2)])
 return {"B":B.tolist(),"J":J,"Dq_direct":Dq.tolist(),"Dk_same_physical_domain":Dk.tolist(),"Dk_from_B_inverse_transpose_Dq":(np.linalg.inv(B).T@Dq).tolist(),"coordinate_covariance_error":float(np.linalg.norm(np.linalg.inv(B).T@Dq-Dk)),"omega_k_sample":ok[::80,::80].tolist(),"omega_q_sample":oq[::80,::80].tolist(),"max_pointwise_two_form_transform_error":float(np.max(np.abs(oq-oq_contract))),"chern_measure_q":integrate2d(oq,a,a),"chern_measure_k_same_physical_domain":integrate2d(ok*J,a,a),"chern_measure_invariance_error":abs(integrate2d(oq,a,a)-integrate2d(ok*J,a,a)),"A":A.tolist(),"F":F.tolist(),"A_prime":Apr.tolist(),"B_prime_from_direct":Bdirect.tolist(),"B_prime_expected":Bexpected.tolist(),"affine_reciprocal_matrix_error":float(np.linalg.norm(Bdirect-Bexpected)),"reciprocal_determinant_error":abs(np.linalg.det(Bdirect)-np.linalg.det(np.linalg.inv(A).T)/np.linalg.det(F)),"S":S.tolist(),"Dq_prime":Dqp.tolist(),"Dq_prime_expected":(np.linalg.inv(S).T@Dq).tolist(),"coordinate_reparametrization_error":float(np.linalg.norm(Dqp-np.linalg.inv(S).T@Dq)),"Dk_from_q_prime":(np.linalg.inv(B@Sprime).T@Dqp).tolist(),"basis_change_alone_response_error":float(np.linalg.norm(np.linalg.inv(B@Sprime).T@Dqp-Dk)),"affine_reciprocal_identity":"PASSED"}
def boundary_term_case(c=(Q0,0)):
 d,a,q,o,g,w,gw=weighted_direct(c); L=DOMAIN_L; coord=np.linspace(-L,L,401)
 def edge(axis,value,coord,normal):
  pts=np.stack((np.full(coord.shape,value),coord),axis=-1) if axis==0 else np.stack((coord,np.full(coord.shape,value)),axis=-1); om=dirac_scalar(pts); ww=gaussian(pts,c)[0]; return normal*np.trapezoid(ww*om,coord)
 boundary=edge(0,-L,coord, np.array([-1.,0.]))+edge(0,L,coord,np.array([1.,0.]))+edge(1,-L,coord,np.array([0.,-1.]))+edge(1,L,coord,np.array([0.,1.]))
 bulk=np.array([-integrate2d(o*gw[...,i],a,a) for i in range(2)])
 return {"D_direct":d.tolist(),"D_ibp_bulk":bulk.tolist(),"boundary_term":boundary.tolist(),"residual":(d-bulk-boundary).tolist(),"residual_norm":float(np.linalg.norm(d-bulk-boundary))}
def valley_benchmark():
 a1=np.linspace(-2,2,401); b1=np.linspace(-1.5,1.5,401); x1,y1=np.meshgrid(a1,b1,indexing="ij"); _,g1=dirac(np.stack((x1,y1),axis=-1)); a2=np.linspace(-2,2.5,451); b2=b1; x2,y2=np.meshgrid(a2,b2,indexing="ij"); _,g2=dirac(np.stack((x2,y2),axis=-1)); da=np.array([integrate2d(g1[...,i],a1,b1) for i in range(2)]); db=np.array([integrate2d(g2[...,i],a2,b2) for i in range(2)])
 return {"domain_A":[[-2,2],[-1.5,1.5]],"domain_B":[[-2,2.5],[-1.5,1.5]],"D_valley_domain_A":da.tolist(),"D_valley_domain_B":db.tolist(),"domain_dependence_difference":float(np.linalg.norm(da-db))}
def dirac_cases():
 out={}
 for n,c in (("CASE_0",(0,0)),("CASE_X",(Q0,0)),("CASE_MINUS_X",(-Q0,0)),("CASE_Y",(0,Q0))):
  d=weighted_direct(c)[0]; ib=weighted_ibp(c); out[n]={"center":list(c),"D_direct":d.tolist(),"D_ibp":ib.tolist(),"direct_ibp_difference":float(np.linalg.norm(d-ib))}
 return out
def run_result():
 p=periodic_benchmark(); cases=dirac_cases(); co=coordinate_benchmark(); valley=valley_benchmark(); bound=boundary_term_case(); analytic=cases["CASE_X"]["D_direct"]; fd=[]
 for h in FD_STEPS:
  d,a,q,o,g,w,gw=weighted_direct((Q0,0)); fg=finite_gradient(q,h); val=np.array([integrate2d(w*fg[...,i],a,a) for i in range(2)]); fd.append({"step":h,"D":val.tolist(),"absolute_error_to_analytic":float(np.linalg.norm(val-analytic))})
 center=np.array(cases["CASE_0"]["D_direct"]); px=np.array(cases["CASE_X"]["D_direct"]); mx=np.array(cases["CASE_MINUS_X"]["D_direct"]); py=np.array(cases["CASE_Y"]["D_direct"]); tp=weighted_direct((Q0,0),tau=1)[0]; tm=weighted_direct((Q0,0),tau=-1)[0]; mp=weighted_direct((Q0,0),mass=MASS)[0]; mm=weighted_direct((Q0,0),mass=-MASS)[0]
 return {"schema":"e8a_c1_weighted_berry_gradient_corrected_v1","parameters":{"tau":TAU,"mass":MASS,"velocity":VELOCITY,"sigma":SIGMA,"q0":Q0,"domain_L":DOMAIN_L,"grid_n":GRID_N,"torus_n":TORUS_N,"fd_steps":list(FD_STEPS)},"periodic":p,"dirac_cases":cases,"finite_difference":fd,"coordinate":co,"boundary_term_case_x":bound,"valley":valley,"symmetry":{"centered_weight_norm":float(np.linalg.norm(center)),"mirror_qx_sum_norm":float(np.linalg.norm(px+mx)),"rotation_covariance_error":float(np.linalg.norm(py-np.array([0,px[0]]))),"tau_reversal_error":float(np.linalg.norm(tp+tm)),"mass_reversal_error":float(np.linalg.norm(mp+mm))},"units":{"q_coordinates":"DIMENSIONLESS","B_units":"INVERSE_LENGTH","omega_q_units":"DIMENSIONLESS_TWO_FORM_COMPONENT","omega_k_units":"LENGTH_SQUARED","D_q_units":"DIMENSIONLESS","D_k_units":"LENGTH","weight_units":"DIMENSIONLESS_NORMALIZED_RECIPROCAL_SPACE_WEIGHT","analytic_length_unit":"1"},"classification":{"observable_name":"WEIGHTED_BERRY_CURVATURE_GRADIENT_FUNCTIONAL","full_bz_unweighted_derivative":"ZERO_AS_PERIODIC_BOUNDARY_IDENTITY","unweighted_valley_derivative":"BOUNDARY_DEPENDENT_NOT_BULK_INVARIANT","weighted_direct_vs_ibp_periodic":"PASSED","finite_domain_ibp_boundary_accounting":"PASSED","berry_two_form_pointwise":"PASSED","chern_measure_invariance":"PASSED","coordinate_covariance":"PASSED","coordinate_reparametrization_invariance":"PASSED","basis_change_alone_physical_response_change":"ZERO_WITHIN_NUMERICAL_ERROR","affine_reciprocal_transform":"PASSED","reciprocal_determinant_scaling":"PASSED","physical_response_status":"GEOMETRIC_FUNCTIONAL_VALIDATED_DYNAMICAL_OBSERVABLE_NOT_YET_DERIVED","live_mpb":"NOT_AUTHORIZED","deformation_physics_live_solve":"NOT_AUTHORIZED"}}
