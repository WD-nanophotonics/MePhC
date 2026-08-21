from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json, os, subprocess, sys, time

ROOT=Path(__file__).parent; GEOM=json.loads((ROOT/'.e7i1g_c1_exact_geometry.json').read_text()); BASE=json.loads((ROOT/'.e7i1g_geometry.json').read_text()); OLD=json.loads((ROOT/'.e7i1g_results'/'manifest.json').read_text()); OUT=ROOT/'.e7i1g_c1_results'; OUT.mkdir(exist_ok=True); MAN=OUT/'manifest.json'; EPS=1e-9; WORKERS=int(os.environ.get('C1_WORKERS','10'))
def key(x,y): return (round(float(x),10),round(float(y),10))
def cen(p): return [sum(q[0] for q in p)/3.,sum(q[1] for q in p)/3.]
def three(p):
    a,b,c=p
    return [[(2*a[0]+b[0]+c[0])/4.,(2*a[1]+b[1]+c[1])/4.],[(a[0]+2*b[0]+c[0])/4.,(a[1]+2*b[1]+c[1])/4.],[(a[0]+b[0]+2*c[0])/4.,(a[1]+b[1]+2*c[1])/4.]]
def area(p):
    a,b,c=p; return abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2.
old={key(t['qx'],t['qy']):t['result'] for t in OLD['tasks'] if t.get('valley')=='K' and t.get('resolution')==64 and abs(t.get('h',0)-.001)<EPS and abs(t.get('radius_a',0)-.15)<EPS and abs(t.get('radius_b',0)-.25)<EPS and t.get('result')}
samples={}; plans=[]
def add(rule,i,j,q,w,a):
    sk=key(*q); sid=f'{rule}:{i}:{j}'; plans.append({'id':sid,'rule':rule,'triangle_index':i,'sample_index':j,'qx':q[0],'qy':q[1],'weight':w,'triangle_area':a,'sample_key':sk}); samples.setdefault(sk,{'qx':q[0],'qy':q[1],'uses':[]})['uses'].append(sid)
for i,tri in enumerate(GEOM['triangles']):
    p=[GEOM['points_offset_K'][j] for j in tri]; add('refined_centroid',i,0,cen(p),1.,area(p))
for i,tri in enumerate(BASE['fine']['triangles']):
    p=[BASE['fine']['points_offset_K'][j] for j in tri]; add('fine_centroid',i,0,cen(p),1.,area(p))
    for j,q in enumerate(three(p)): add('fine_three_point',i,j,q,1/3.,area(p))
reuse={}; fresh=[]
if MAN.exists(): previous=json.loads(MAN.read_text())
else: previous={'samples':[]}
checkpoint={key(t['qx'],t['qy']):t['result'] for t in previous.get('samples',[]) if t.get('result')}
for sk,s in samples.items():
    if sk in checkpoint: reuse[sk]=checkpoint[sk]
    elif sk in old: reuse[sk]=old[sk]
    else: fresh.append((sk,s))
def solve(item):
    sk,s=item; cmd=[sys.executable,str(ROOT/'e7i1b_point_worker.py'),'--resolution','64','--h','.001','--qx',repr(s['qx']),'--qy',repr(s['qy']),'--valley','K','--radius-a','.15','--radius-b','.25']; started=time.time()
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=180); result=None
        for line in reversed(p.stdout.splitlines()):
            if line.strip().startswith('{'):
                try:
                    obj=json.loads(line)
                    if obj.get('event')=='result': result=obj; break
                except json.JSONDecodeError: pass
        return sk,{'complete':result is not None,'result':result,'elapsed_seconds':time.time()-started,'error':p.stderr[-2000:] if result is None else ''}
    except Exception as exc: return sk,{'complete':False,'result':None,'elapsed_seconds':time.time()-started,'error':repr(exc)}
completed=dict(reuse); manifest={'version':2,'status':'RUNNING','baseline_commit':OLD['baseline_commit'],'geometry':'exact_voronoi_piece_triangulation','workers':WORKERS,'plans':plans,'samples':[],'fresh_count':len(fresh),'reused_count':len(reuse),'checkpoint_reuse_count':len(checkpoint),'started_at':time.time()}
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    futures=[pool.submit(solve,item) for item in fresh]
    for n,f in enumerate(as_completed(futures),1):
        sk,rec=f.result(); completed[sk]=rec['result']
        if n%512==0 or n==len(futures):
            manifest['completed_fresh']=n; manifest['samples']=[{'qx':s['qx'],'qy':s['qy'],'result':completed.get(sk),'execution':'REUSED_STORED' if sk in reuse else 'FRESH_CHILD','sample_key':sk} for sk,s in samples.items()]; MAN.write_text(json.dumps(manifest)); print(json.dumps({'event':'c1_quadrature_progress','fresh_completed':n,'fresh_total':len(fresh),'sample_total':len(samples)}),flush=True)
manifest['status']='COMPLETE' if all(completed.get(sk) is not None for sk in samples) else 'FAILED_INCOMPLETE'; manifest['samples']=[{'qx':s['qx'],'qy':s['qy'],'result':completed.get(sk),'execution':'REUSED_STORED' if sk in reuse else 'FRESH_CHILD','sample_key':sk} for sk,s in samples.items()]; manifest['finished_at']=time.time(); manifest['qualified_count']=sum(r is not None and r.get('production_decision')=='QUALIFIED_VALUE' for r in completed.values()); manifest['masked_count']=sum(r is not None and r.get('production_decision')!='QUALIFIED_VALUE' for r in completed.values()); MAN.write_text(json.dumps(manifest,indent=2)); print(json.dumps({'event':'c1_quadrature_complete','status':manifest['status'],'plans':len(plans),'unique_samples':len(samples),'fresh':len(fresh),'reused':len(reuse),'qualified':manifest['qualified_count'],'masked':manifest['masked_count']},indent=2),flush=True)
