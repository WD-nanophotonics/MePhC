from pathlib import Path
here=Path(__file__).parent
source=(here/'e7i1g_c1_quadrature_supervisor_v2.py').read_text()
source=source.replace("'.e7i1g_c1_exact_geometry.json'","'.e7i1g_c1_exact_geometry_fixed.json'")
source=source.replace("OUT=ROOT/'.e7i1g_c1_results'","OUT=ROOT/'.e7i1g_c1_results_fixed'")
exec(compile(source,'e7i1g_c1_quadrature_supervisor_v2.py','exec'),{'__name__':'__main__','__file__':str(here/'e7i1g_c1_quadrature_supervisor_v2.py')})
