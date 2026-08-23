import ast,json,sys
from pathlib import Path
import numpy as np
from .weighted_berry_gradient import *
def self_check():
 src=Path(__file__).with_name("weighted_berry_gradient.py").read_text(); tree=ast.parse(src); mods=[n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]; assert not any(any(t in x.lower() for t in ("meep","mpb","berry","chern","wilson")) for x in mods)
 assert (TAU,MASS,VELOCITY,SIGMA,Q0)==(1,.7,1.3,.8,1); p=periodic_benchmark(); assert np.linalg.norm(p["full_derivative"])<1e-10 and p["direct_ibp_error"]<1e-10; c=dirac_cases(); assert all(v["direct_ibp_difference"]<5e-6 for v in c.values()); assert np.linalg.norm(c["CASE_0"]["D_direct"])<5e-7; assert valley_benchmark()["domain_dependence_difference"]>1e-4; co=coordinate_benchmark(); assert co["max_pointwise_two_form_transform_error"]<1e-14 and co["chern_measure_invariance_error"]<1e-12 and co["coordinate_covariance_error"]<1e-10 and co["affine_reciprocal_matrix_error"]<1e-12 and co["reciprocal_determinant_error"]<1e-12 and co["coordinate_reparametrization_error"]<1e-10 and co["basis_change_alone_response_error"]<1e-10; assert boundary_term_case()["residual_norm"]<1e-10
def run(out):
 self_check(); d=run_result(); d["self_checks"]="PASSED"; out.write_text(json.dumps(d,sort_keys=True,indent=2)+chr(10)); return d
if __name__=="__main__":
 if "--self-check" in sys.argv: self_check(); print("E8A_C1_SELF_CHECK=PASS")
 else:
  o=Path(sys.argv[sys.argv.index("--output")+1]) if "--output" in sys.argv else Path("audit/e8a/result.json"); d=run(o); print(json.dumps({"schema":d["schema"],"self_checks":d["self_checks"]}))
