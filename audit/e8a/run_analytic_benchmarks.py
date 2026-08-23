import ast,json
from pathlib import Path
import numpy as np
from .weighted_berry_gradient import *
def self_check():
 src=Path(__file__).with_name("weighted_berry_gradient.py").read_text()
 tree=ast.parse(src)
 imports=[n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
 assert not any(any(t in x.lower() for t in ("meep","mpb","berry","chern","wilson")) for x in imports)
 assert (TAU,MASS,VELOCITY,SIGMA,Q0)==(1.0,0.7,1.3,0.8,1.0)
 p=periodic_benchmark(); assert np.linalg.norm(p["full_derivative"])<1e-10 and p["direct_ibp_error"]<1e-10
 c=dirac_cases(); assert all(x["direct_ibp_difference"]<5e-6 for x in c.values())
 a=weighted_direct((0,0))[0]; assert np.linalg.norm(a)<5e-7
 _,q=grid(); assert abs(integrate2d(gaussian(q,(0,0))[0],*grid()[:1],*grid()[:1])-1)<1e-8
 assert valley_benchmark()["domain_dependence_difference"]>1e-4
def run(out):
 self_check(); data=run_result(); data["self_checks"]="PASSED"; out.write_text(json.dumps(data,sort_keys=True,indent=2)+chr(10)); return data
if __name__=="__main__":
 import sys
 if "--self-check" in sys.argv: self_check(); print("E8A_SELF_CHECK=PASS")
 else:
  out=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else Path("audit/e8a/result.json")
  d=run(out); print(json.dumps({"schema":d["schema"],"self_checks":d["self_checks"]}))
