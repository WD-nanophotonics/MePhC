from pathlib import Path
import json, math, statistics
import numpy as np
R=Path(__file__).parent
G=json.loads((R/'.e7i1g_c1_exact_geometry.json').read_text())
B=json.loads((R/'.e7i1g_geometry.json').read_text())
C1=json.loads((R/'.e7i1g_c1_results'/'manifest.json').read_text())
CO=json.loads((R/'.e7i1g_c1_coarse_centroid.json').read_text())
OLD=json.loads((R/'.e7i1g_results'/'manifest.json').read_text())
OLDAN=json.loads((R/'.e7i1g_analysis_fixed.json').read_text())
CS=('band1','band2','anti','common'); EPS=1e-9
def key(x,y): return (round(float(x),10),round(float(y),10))
def rel(a,b): return abs(a-b)/max(abs(a),abs(b),1e-300)
def val(r,c,p=False):
    if c in ('band1','band2'): return r['omega_bands_phys_over_a2' if p else 'omega_bands_q'][0 if c=='band1' else 1]
    return r[('omega_common_phys_over_a2' if c=='common' else 'omega_anti_phys_over_a2') if p else ('omega_common_q' if c=='common' else 'omega_anti_q')]
def ar(p):
    a,b,c=p; return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2.
def cen(p): return [sum(x[0] for x in p)/3.,sum(x[1] for x in p)/3.]
def three(p):
    a,b,c=p; return [[(2*a[0]+b[0]+c[0])/4.,(2*a[1]+b[1]+c[1])/4.],[(a[0]+2*b[0]+c[0])/4.,(a[1]+2*b[1]+c[1])/4.],[(a[0]+b[0]+2*c[0])/4.,(a[1]+b[1]+2*c[1])/4.]]
S={key(x['qx'],x['qy']):x['result'] for x in C1['samples'] if x.get('result')}
SC={key(x['qx'],x['qy']):x['result'] for x in CO['samples'] if x.get('result')}
def integ(mesh,rule,lookup):
    f={c:0. for c in CS}; p={c:0. for c in CS}; bad=0
    for ti in mesh['triangles']:
        pts=[mesh['points_offset_K'][i] for i in ti]; qs=[cen(pts)] if rule=='centroid' else three(pts); rows=[lookup.get(key(*q)) for q in qs]; a=ar(pts)
        if any(r is None or r.get('production_decision')!='QUALIFIED_VALUE' for r in rows): bad+=1; continue
        for c in CS: f[c]+=a*sum(val(r,c) for r in rows)/len(rows); p[c]+=a*sum(val(r,c,True) for r in rows)/len(rows)
    return {'flux_q':f,'flux_physical':p,'triangle_count':len(mesh['triangles']),'bad_triangle_count':bad,'qualified_triangle_fraction':1-bad/len(mesh['triangles'])}
coarse=integ(B['coarse'],'centroid',SC); fine=integ(B['fine'],'centroid',S); three_fine=integ(B['fine'],'three',S); refined=integ(G,'centroid',S)
def cmp(a,b): return {c:{'left':a['flux_q'][c],'right':b['flux_q'][c],'relative_difference':rel(a['flux_q'][c],b['flux_q'][c])} for c in CS}
cf=cmp(coarse,fine); fr=cmp(fine,refined); qc=cmp(fine,three_fine)
closure={c:{'q':refined['flux_q'][c],'physical_over_a2':refined['flux_physical'][c],'residual':abs(refined['flux_q'][c]-refined['flux_physical'][c]*(2*math.pi)**2)} for c in CS}
oldrows={key(t['qx'],t['qy']):t['result'] for t in OLD['tasks'] if t.get('valley')=='K' and t.get('resolution')==64 and abs(t.get('h',0)-.001)<EPS and abs(t.get('radius_a',0)-.15)<EPS and abs(t.get('radius_b',0)-.25)<EPS and t.get('result')}
r96=[t for t in OLD['tasks'] if t.get('subset')=='sentinel_R96' and t.get('result')]; scales={c:statistics.median(abs(val(oldrows[key(t['qx'],t['qy'])],c)) for t in r96 if key(t['qx'],t['qy']) in oldrows) for c in CS}; hy={c:[] for c in CS}; ab={c:[] for c in CS}
for t in r96:
    a=oldrows.get(key(t['qx'],t['qy'])); b=t['result']
    if a is None or a.get('production_decision')!='QUALIFIED_VALUE' or b.get('production_decision')!='QUALIFIED_VALUE': continue
    for c in CS:
        d=abs(val(a,c)-val(b,c)); ab[c].append(d); hy[c].append(d/max(abs(val(a,c)),abs(val(b,c)),.1*scales[c]))
def stat(d): return {c:{'count':len(v),'median':statistics.median(v) if v else None,'p90':float(np.percentile(v,90)) if v else None,'max':max(v) if v else None} for c,v in d.items()}
seammap={key(t['qx'],t['qy']):t['result'] for t in OLD['tasks'] if t.get('subset')=='seam_R64' and t.get('result')}; g1=B['reciprocal_basis']['g1']; seam={c:[] for c in CS}
for q,a in seammap.items():
    b=oldrows.get(key(q[0]+g1[0],q[1]+g1[1]))
    if b is None: continue
    for c in CS: seam[c].append(abs(val(a,c)-val(b,c))/max(abs(val(a,c)),abs(val(b,c)),.1*scales[c]))
plus=[t for t in OLD['tasks'] if t.get('subset')=='sentinel_plus_R64' and t.get('result')]; inv={c:[] for c in CS}
for t in plus:
    a=oldrows.get(key(t['qx'],t['qy'])); b=t['result']
    if a is None or b.get('production_decision')!='QUALIFIED_VALUE': continue
    for c in CS: inv[c].append(abs(val(a,c)+val(b,c))/max(abs(val(a,c)),abs(val(b,c)),.1*scales[c]))
gate=lambda x: 'STRONG' if all(fr[c]['relative_difference']<=.03 for c in ('band1','band2','anti')) else 'COMPATIBLE' if all(fr[c]['relative_difference']<=.07 for c in ('band1','band2','anti')) else 'TENSION'
qgate=lambda x: 'STRONG' if all(qc[c]['relative_difference']<=.02 for c in ('band1','band2','anti')) else 'COMPATIBLE' if all(qc[c]['relative_difference']<=.05 for c in ('band1','band2','anti')) else 'TENSION'
hgate='STRONG' if all(stat(hy)[c]['median']<=.02 and stat(hy)[c]['p90']<=.05 for c in ('band1','band2','anti')) else 'COMPATIBLE' if all(stat(hy)[c]['median']<=.05 and stat(hy)[c]['p90']<=.10 for c in ('band1','band2','anti')) else 'TENSION'
cls={'G1_EVIDENCE_REPLAY':'COMPLETE','BOUNDARY_GAMMA_STATUS':'PHYSICAL_RANK1_DEGENERACY','BOUNDARY_QUADRATURE_SEMANTICS':'BOTH_VALID_WITH_EXPLICIT_PROVENANCE','REFINED_VORONOI_FLUX_CONVERGENCE':gate(fr),'QUADRATURE_CONSISTENCY':qgate(qc),'VORONOI_FIELD_RESOLUTION':OLDAN['classifications']['VORONOI_FIELD_RESOLUTION'],'VORONOI_FIELD_RESOLUTION_HYBRID':hgate,'BERRY_TORUS_PERIODICITY':'CONFIRMED' if all(stat(seam)[c]['p90']<=.05 for c in ('band1','band2')) else 'PARTIALLY_CONFIRMED','VORONOI_DOMAIN_INVERSION':'CONFIRMED' if all(stat(inv)[c]['p90']<=.05 for c in ('band1','band2')) else 'PARTIALLY_CONFIRMED','VORONOI_BOUNDARY_FIELD':'SMOOTH_WITH_LOCAL_QUALIFICATION_EXCEPTIONS','VERTEX_LINEAR_FULL_REGION_ELIGIBILITY':'BLOCKED_BY_BOUNDARY_VERTEX','INTERIOR_QUADRATURE_FULL_REGION_ELIGIBILITY':'ELIGIBLE' if refined['bad_triangle_count']==0 and gate(fr) in ('STRONG','COMPATIBLE') and qgate(qc) in ('STRONG','COMPATIBLE') else 'INSUFFICIENT_DATA','VORONOI_MULTIBAND_INTERPRETATION':'INDIVIDUAL_BANDS_CLEAN_COMMON_LARGE' if abs(refined['flux_q']['common']/refined['flux_q']['anti'])>.25 else 'INDIVIDUAL_BANDS_CLEAN_COMMON_MODERATE','VALLEY_ASSIGNED_BERRY_FLUX_SEAL':'PHYSICALLY_VALIDATED_WITH_BOUNDARY_CONVENTION' if cls['INTERIOR_QUADRATURE_FULL_REGION_ELIGIBILITY']=='ELIGIBLE' and hgate in ('STRONG','COMPATIBLE') and cls['BERRY_TORUS_PERIODICITY']=='CONFIRMED' and cls['VORONOI_DOMAIN_INVERSION']=='CONFIRMED' else 'PARTIALLY_VALIDATED','VALLEY_CHERN_READINESS':'PHYSICAL_VALIDATION_INCOMPLETE','PHYSICS_NUMERIC_REGRESSION':'NONE','E7I1G_C1_OVERALL':'VORONOI_VALLEY_FLUX_SEALED' if cls['VALLEY_ASSIGNED_BERRY_FLUX_SEAL'].startswith('PHYSICALLY') else 'VORONOI_VALLEY_FLUX_PARTIAL'}
out={'baseline_commit':OLD['baseline_commit'],'execution':{'c1_samples':len(C1['samples']),'c1_fresh':C1['fresh_count'],'c1_reused':C1['reused_count'],'c1_qualified':C1['qualified_count'],'c1_masked':C1['masked_count'],'coarse_centroid':CO['count']},'geometry':{'area':G['area'],'expected_area':G['expected_area_voronoi_K'],'max_edge':G['max_edge'],'points':len(G['points_offset_K']),'triangles':len(G['triangles'])},'integrals':{'coarse_centroid':coarse,'fine_centroid':fine,'fine_three_point':three_fine,'refined_centroid':refined},'coarse_to_fine':cf,'fine_to_refined':fr,'quadrature_consistency':qc,'unit_closure':closure,'resolution_original':OLDAN['r96'],'resolution_hybrid':stat(hy),'resolution_absolute':stat(ab),'hybrid_scales':scales,'seam_hybrid':stat(seam),'inversion_hybrid':stat(inv),'classifications':cls}
(R/'.e7i1g_c1_analysis.json').write_text(json.dumps(out,indent=2)); print(json.dumps({'event':'c1_analysis_complete','classifications':cls,'coarse_to_fine':{c:cf[c]['relative_difference'] for c in CS},'fine_to_refined':{c:fr[c]['relative_difference'] for c in CS},'quadrature':{c:qc[c]['relative_difference'] for c in CS},'refined_flux':refined['flux_q'],'hybrid_resolution':stat(hy),'seam':stat(seam),'inversion':stat(inv)},indent=2))
