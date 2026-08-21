from pathlib import Path
import json
root=Path(__file__).parent
old=json.loads((root/'.e7i1g_c1_exact_geometry.json').read_text())
K=old['K']
absolute=old['points_offset_K']
offset=[[p[0]-K[0],p[1]-K[1]] for p in absolute]
fixed=dict(old)
fixed['points_abs']=absolute
fixed['points_offset_K']=offset
fixed['coordinate_fix']='pieces were absolute-q; points_offset_K corrected by subtracting K'
(root/'.e7i1g_c1_exact_geometry_fixed.json').write_text(json.dumps(fixed,indent=2))
print(json.dumps({'event':'c1_geometry_coordinate_fix','points':len(offset),'triangles':len(fixed['triangles']),'area':fixed['area'],'expected':fixed['expected_area_voronoi_K']},indent=2))
