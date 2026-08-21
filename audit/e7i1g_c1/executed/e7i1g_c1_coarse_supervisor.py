from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json, os, subprocess, sys, time
root=Path(__file__).parent; geom=json.loads((root/'.e7i1g_geometry.json').read_text()); c1=json.loads((root/'.e7i1g_c1_results'/'manifest.json').read_text()); out=root/'.e7i1g_c1_coarse_centroid.json'
def key(x,y): return (round(float(x),10),round(float(y),10))
samples=[]
for i,tri in enumerate(geom['coarse']['triangles']):
    p=[geom['coarse']['points_offset_K'][j] for j in tri]; q=[sum(x[0] for x in p)/3.,sum(x[1] for x in p)/3.]; samples.append({'index':i,'qx':q[0],'qy':q[1]})
existing={key(x['qx'],x['qy']):x['result'] for x in c1['samples'] if x.get('result')}
def solve(s):
    if key(s['qx'],s['qy']) in existing: return s,existing[key(s['qx'],s['qy'])],'REUSED_C1'
    env=os.environ.copy(); env.update({'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
    cmd=[sys.executable,str(root/'e7i1b_point_worker.py'),'--resolution','64','--h','.001',f"--qx={s['qx']}",f"--qy={s['qy']}",'--valley','K','--radius-a','.15','--radius-b','.25']
    p=subprocess.run(cmd,capture_output=True,text=True,check=True,env=env); r=None
    for line in reversed(p.stdout.splitlines()):
        if line.strip().startswith('{'):
            try:
                obj=json.loads(line)
                if obj.get('event')=='result': r=obj; break
            except json.JSONDecodeError: pass
    if r is None: raise RuntimeError(f"no result for {s}")
    return s,r,'FRESH_CHILD'
results=[]
with ThreadPoolExecutor(max_workers=10) as pool:
    fs=[pool.submit(solve,s) for s in samples]
    for f in as_completed(fs): results.append(f.result())
results.sort(key=lambda x:x[0]['index'])
payload={'status':'COMPLETE','resolution':64,'h':.001,'count':len(results),'fresh_count':sum(x[2]=='FRESH_CHILD' for x in results),'reused_count':sum(x[2]!='FRESH_CHILD' for x in results),'samples':[{'index':s['index'],'qx':s['qx'],'qy':s['qy'],'execution':mode,'result':r} for s,r,mode in results]}
out.write_text(json.dumps(payload,indent=2)); print(json.dumps({'event':'c1_coarse_centroid_complete','count':len(results),'fresh':payload['fresh_count'],'reused':payload['reused_count'],'qualified':sum(x['result'].get('production_decision')=='QUALIFIED_VALUE' for x in payload['samples'])},indent=2))
