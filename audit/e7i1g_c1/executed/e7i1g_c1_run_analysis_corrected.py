from pathlib import Path

root = Path(__file__).resolve().parent
source_path = root / "e7i1g_c1_analysis2.py"
source = source_path.read_text(encoding="utf-8")
source = source.replace(".e7i1g_c1_exact_geometry.json", ".e7i1g_c1_exact_geometry_fixed.json")
source = source.replace(".e7i1g_c1_results", ".e7i1g_c1_results_fixed")
# The deduplicated seam sample set contains the translated/right representatives;
# pair them with the left counterpart at q-g1.
source = source.replace("oldrows.get(key(q[0]+g1[0],q[1]+g1[1]))", "oldrows.get(key(q[0]-g1[0],q[1]-g1[1]))")
# The original analysis script self-referenced `cls` while constructing it.
# Keep the numeric evidence generation intact and defer the final classification
# to the post-run audit.
source = source.replace("cls['INTERIOR_QUADRATURE_FULL_REGION_ELIGIBILITY']", "'DEFERRED'")
source = source.replace("cls['BERRY_TORUS_PERIODICITY']", "'DEFERRED'")
source = source.replace("cls['VORONOI_DOMAIN_INVERSION']", "'DEFERRED'")
source = source.replace("cls['VALLEY_ASSIGNED_BERRY_FLUX_SEAL'].startswith('PHYSICALLY')", "False")
exec(compile(source, str(source_path), "exec"), {"__file__": str(source_path), "__name__": "__main__"})
