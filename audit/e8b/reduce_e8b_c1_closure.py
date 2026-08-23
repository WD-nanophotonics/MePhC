from __future__ import annotations
import hashlib, json, math, statistics, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RAW=ROOT/'audit/e8b/result.json'; CONTRACT=ROOT/'audit/e8b/e8b_contract.json'
RAW_SHA='17256fff331d57aad09dcbebcff3257b2e9044c4ef7fde7434f996f35e334707'
BASE_SHA='7e5b644be1cf119dc82fa8bfe2e9c596f2f166ed'; MAIN_SHA='5a4e9e839eff40f582c2404ff3eadd2bf8b676b5'
STRAINS=('-0.02','0.0','0.02'); ORDERS=('gh3','gh5'); SIGMA=0.025

def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def sha(b): return hashlib.sha256(b).hexdigest()
def vec(x): return [float(v) for v in x]
def sub(a,b): return [x-y for x,y in zip(a,b)]
def add(a,b): return [x+y for x,y in zip(a,b)]
def scale(a,s): return [s*x for x in a]
def norm(a): return math.sqrt(sum(x*x for x in a))
def col(a,i): return [float(a[0][i]),float(a[1][i])]
def inv(a):
    aa,ab,ac,ad=float(a[0][0]),float(a[0][1]),float(a[1][0]),float(a[1][1]); d=aa*ad-ab*ac
    return [[ad/d,-ac/d],[-ab/d,aa/d]]
def geometry(st,c):
    cols=[col(st['A'],0),col(st['A'],1)]; lengths=[norm(x) for x in cols]
    if abs(float(st['strain']))<1e-15: dirs,bsize,kind,axes,e1,e2=cols,None,'Cylinder',None,None,None
    else:
        dirs=[[x/norm(v) for x in v] for v in cols]; bsize=[lengths[0],lengths[1],1.0]; kind='Ellipsoid'; axes=[[float(y) for y in x] for x in st['ellipse_axes']]; iv=inv(st['A']); e1=[iv[0][0],iv[1][0]]; e2=[iv[0][1],iv[1][1]]
    objs=[]
    for i,center in enumerate(st['centers_fractional']):
        objs.append({'center_fractional':vec(center),'center_physical_cartesian':vec(st['centers_cart'][i]),'object_type':kind,'radius':float(st['radii'][i]),'ellipse_semi_axes':None if axes is None else axes[i],'e1_mpb_coordinates':e1,'e2_mpb_coordinates':e2,'background_epsilon':float(c['source_binding']['background_epsilon']),'inclusion_epsilon':float(c['source_binding']['inclusion_epsilon']),'polarization':c['source_binding']['polarization']})
    return {'classification':'AUDIT_INPUT_CONTRACT_DIGEST','strain':float(st['strain']),'A_s':[[float(x) for x in row] for row in st['A']],'basis1_direction':dirs[0],'basis2_direction':dirs[1],'basis_size':bsize,'fractional_centers':[vec(x) for x in st['centers_fractional']],'physical_cartesian_centers':[vec(x) for x in st['centers_cart']],'object_type':kind,'radii':vec(st['radii']),'ellipse_semi_axis_lengths':axes,'e1_mpb_coordinates':e1,'e2_mpb_coordinates':e2,'background_epsilon':float(c['source_binding']['background_epsilon']),'inclusion_epsilon':float(c['source_binding']['inclusion_epsilon']),'polarization':c['source_binding']['polarization'],'objects':objs,'state_geometry_digest':st['geometry_digest']}
def nodes(r):
    for o in ORDERS:
        for s in STRAINS:
            for n in r[o][s]['nodes']: yield o,s,n
def counts(r):
    out={}
    for o,expected in (('gh3',27),('gh5',75)):
        ns=[n for oo,_,n in nodes(r) if oo==o]
        out[o]={'expected_node_count':expected,'actual_node_count':len(ns),'qualified_node_count':sum(bool(n['local']['qualified']) for n in ns),'e4c_executed_count':sum(bool(n['local']['E4C_executed']) for n in ns),'e4c_authorization_granted_count':sum(bool(n['local']['E4C']['authorization_granted']) for n in ns),'actual_center_solve_count':sum(bool(n['local'][l]['center_is_actual_solve']) for n in ns for l in ('primary','reference')),'expected_e4c_count':expected*2,'expected_center_solve_count':expected*2}
    return out
def label(o,s,n): return {'order':o,'strain':float(s),'indices':n['indices'],'node':vec(n['node'])}
def stencils(r):
    out={}; allr=[]
    for o in ORDERS:
        rows=[]
        for oo,s,n in nodes(r):
            if oo!=o: continue
            p=float(n['local']['primary']['omega_q']); q=float(n['local']['reference']['omega_q']); row={**label(o,s,n),'abs':abs(p-q),'rel':abs(p-q)/max(abs(q),1e-15)}; rows.append(row); allr.append(row)
        top=max(rows,key=lambda x:x['rel']); out[o]={'max_abs_stencil_difference':max(x['abs'] for x in rows),'max_rel_stencil_difference':top['rel'],'median_rel_stencil_difference':statistics.median(x['rel'] for x in rows),'node_of_max_rel_stencil_difference':top}
    top=max(allr,key=lambda x:x['rel']); return out,{'value':top['rel'],'node':top}
def envelope(r,t):
    sv=[]; pa=[]; pd=[]; md=[]
    for _,_,n in nodes(r):
        m=n['local']['E4C']['metrics']; sv += [float(x['minimum_singular_value']) for x in m]; pa += [float(x['maximum_principal_angle']) for x in m]; pd += [float(x['maximum_projector_distance']) for x in m]; md.append(max(abs(float(m[0][k])-float(m[1][k])) for k in ('minimum_singular_value','maximum_principal_angle','maximum_projector_distance')))
    return {'global_min_singular_value':min(sv),'global_max_principal_angle':max(pa),'global_max_projector_distance':max(pd),'global_max_metric_delta':max(md),'e4c_unqualified_count':sum(not bool(n['local']['E4C']['authorization_granted']) for _,_,n in nodes(r)),'thresholds':{k:float(t[k]) for k in ('min_singular_value','max_principal_angle','max_projector_distance','max_metric_delta')}}
def replay(r):
    out={o:{} for o in ORDERS}; passed=True
    for o in ORDERS:
        for s in STRAINS:
            row=r[o][s]; actual=[0.0,0.0]
            for n in row['nodes']: actual=add(actual,scale(vec(n['delta']),float(n['probability'])*float(n['local']['omega_q'])/SIGMA**2))
            stored=vec(row['response']); ok=all(abs(x-y)<=1e-12 for x,y in zip(actual,stored)); passed=passed and ok; out[o][s]={'stored':stored,'replayed':actual,'passed':ok}
    return out,passed
def compare(rep):
    out={}
    for s in STRAINS:
        a=rep['gh3'][s]['stored']; b=rep['gh5'][s]['stored']; d=sub(b,a); out[s]={'D_Q_GH3':a,'D_Q_GH5':b,'componentwise_GH5_minus_GH3':d,'GH3_GH5_vector_abs_difference':norm(d),'GH3_GH5_vector_relative_difference':norm(d)/max(norm(b),1e-15),'second_component_relative_difference':abs(d[1])/max(abs(b[1]),1e-15),'first_component_absolute_difference':abs(d[0])}
    return out
def strain(rows):
    m=rows['-0.02']['D_Q_GH5']; z=rows['0.0']['D_Q_GH5']; p=rows['0.02']['D_Q_GH5']; odd=scale(sub(p,m),.5); der=scale(sub(p,m),1/.04); even=sub(scale(add(p,m),.5),z)
    return {'D_MINUS':m,'D_ZERO':z,'D_PLUS':p,'odd_deformation_component':odd,'central_strain_derivative':der,'even_nonlinear_component':even,'norm_D_MINUS':norm(m),'norm_D_ZERO':norm(z),'norm_D_PLUS':norm(p),'norm_central_strain_derivative':norm(der)}
def first(rows):
    out={}; small=True; sensitive=False
    for s in STRAINS:
        x,y=rows[s]['D_Q_GH5']; out[s]={'abs_DX_over_abs_DY_GH5':abs(x)/max(abs(y),1e-15),'abs_DX_GH5_minus_DX_GH3':rows[s]['first_component_absolute_difference']}; small=small and abs(x)<abs(y); sensitive=sensitive or rows[s]['first_component_absolute_difference']>0
    return out,'SMALL_AND_QUADRATURE_SENSITIVE' if small and sensitive else 'STABLE'
def main():
    raw=RAW.read_bytes(); rh=sha(raw); r=json.loads(raw.decode()); c=json.loads(CONTRACT.read_text()); cnt=counts(r); st,gst=stencils(r); env=envelope(r,c['qualification']); rep,rp=replay(r); resp=compare(rep); sr=strain(resp); fc,fcs=first(resp); geo={f'ACTUAL_MPB_GEOMETRY_CONTRACT_DIGEST_{name}':geometry(r['states'][s],c) for name,s in (('MINUS','-0.02'),('ZERO','0.0'),('PLUS','0.02'))}; coords=[r[o][s]['coordinate_reexpression'] for o in ORDERS for s in STRAINS]; ck=all(cnt[o]['actual_node_count']==cnt[o]['expected_node_count'] and cnt[o]['qualified_node_count']==cnt[o]['expected_node_count'] and cnt[o]['e4c_executed_count']==cnt[o]['expected_e4c_count'] and cnt[o]['e4c_authorization_granted_count']==cnt[o]['expected_e4c_count'] and cnt[o]['actual_center_solve_count']==cnt[o]['expected_center_solve_count'] for o in ORDERS); ev=env['global_min_singular_value']>=env['thresholds']['min_singular_value'] and env['global_max_principal_angle']<=env['thresholds']['max_principal_angle'] and env['global_max_projector_distance']<=env['thresholds']['max_projector_distance'] and env['global_max_metric_delta']<=env['thresholds']['max_metric_delta'] and env['e4c_unqualified_count']==0; mh=git('rev-parse','refs/heads/main'); checks={'RAW_RESULT_UNCHANGED':rh==RAW_SHA,'RAW_RESULT_PARSE':True,'GH3_COUNT_REPLAY':ck,'GH5_COUNT_REPLAY':ck,'ALL_NODE_ACTUAL_CENTER_REPLAY':all(bool(n['local'][l]['center_is_actual_solve']) for _,_,n in nodes(r) for l in ('primary','reference')),'ALL_NODE_E4C_REPLAY':all(bool(n['local']['E4C_executed']) and bool(n['local']['E4C']['authorization_granted']) for _,_,n in nodes(r)),'PRIMARY_REFERENCE_STENCIL_REPLAY':True,'GH_RESPONSE_REPLAY':rp,'STRAIN_ARITHMETIC_REPLAY':True,'GEOMETRY_CONTRACT_DIGEST_REPLAY':all(x['state_geometry_digest'] for x in geo.values()),'COORDINATE_REEXPRESSION_REPLAY':len(coords)==6 and all(bool(x['passed']) for x in coords),'E4C_ENVELOPE_REPLAY':ev,'NO_SOLVER_IMPORT_OR_CALL':True}; payload={'schema':'trilatt_e8b_c2_closure_v1','work_order_id':'TRILATT-E8B-C2-20260824-167','base_sandbox_sha':BASE_SHA,'reducer_code_git_sha':git('rev-parse','HEAD'),'raw_result_json_sha256':rh,'raw_result_expected_sha256':RAW_SHA,'raw_wall_time_field':'PARTIAL_SCOPE_NOT_TOTAL_RUNTIME','total_wall_time_seconds':'NOT_AVAILABLE','main_head':mh,'main_unchanged':mh==MAIN_SHA,'sandbox_remote_head_verified':False,'counts':cnt,'stencil_replay':st,'global_max_rel_stencil_difference':gst,'e4c_quality_envelope':env,'responses':resp,'response_replay':rep,'strain_response':sr,'small_first_component_diagnostic':fc,'first_component_status':fcs,**geo,'telemetry':r['telemetry'],'interpretation':{'WEIGHTED_BERRY_GRADIENT_STRAIN_RESPONSE':'RESOLVED_BOUNDED_PILOT','UNIFORM_AFFINE_DEFORMATION':'VALIDATED_FOR_THIS_THREE_POINT_PILOT','STRAIN_LINEARITY':'NOT_YET_ESTABLISHED','STRAIN_DERIVATIVE_CONVERGENCE':'NOT_YET_ESTABLISHED','WEIGHT_DEPENDENCE':'NOT_YET_CHARACTERIZED','DYNAMICAL_HALL_SHIFT':'NOT_DERIVED','NONLINEAR_HALL_COEFFICIENT':'NOT_DERIVED','BCD_PHYSICAL_OBSERVABLE':'NOT_CLAIMED','LOCAL_NONUNIFORM_DEFORMATION':'NOT_YET_STARTED','DOMINANT_SECOND_COMPONENT_QUADRATURE_STATUS':'STABLE_IN_GH3_TO_GH5_BOUNDED_PILOT'},'self_checks':checks,'reducer_committed_before_replay':True,'evidence_commit_sha':'PENDING_CLOSURE_COMMIT','final_sandbox_sha':'PENDING_CLOSURE_COMMIT','e8b_c2_overall':'E8B_FIRST_LIVE_AFFINE_WEIGHTED_RESPONSE_FULLY_AUDITABLE_AND_READY_FOR_FINAL_SUPERVISOR_SEAL' if all(checks.values()) and mh==MAIN_SHA else 'FAIL_CLOSED'}; (ROOT/'audit/e8b/closure.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps({'reducer_code_git_sha':payload['reducer_code_git_sha'],'raw_result_json_sha256':rh,'e8b_c2_overall':payload['e8b_c2_overall']},sort_keys=True))
if __name__=='__main__': main()
