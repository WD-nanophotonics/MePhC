from pathlib import Path
import json
from shapely.geometry import Polygon
from shapely.ops import triangulate

root = Path(__file__).parent
g = json.loads((root / '.e7i1g_geometry.json').read_text())
limit = 0.015
def edge(a,b): return ((a[0]-b[0])**2+(a[1]-b[1])**2)**.5
def split(tri):
    a,b,c=tri
    ab=((a[0]+b[0])/2,(a[1]+b[1])/2)
    bc=((b[0]+c[0])/2,(b[1]+c[1])/2)
    ca=((c[0]+a[0])/2,(c[1]+a[1])/2)
    return ((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca))
triangles=[]
for piece_coords in g['pieces']:
    piece=Polygon(piece_coords)
    for candidate in triangulate(piece):
        if not piece.covers(candidate) or candidate.area <= 1e-14: continue
        current=[tuple(x) for x in list(candidate.exterior.coords)[:-1]]
        stack=[current]
        while stack:
            tri=stack.pop()
            if max(edge(tri[0],tri[1]),edge(tri[1],tri[2]),edge(tri[2],tri[0])) <= limit+1e-12:
                triangles.append(tri)
            else:
                stack.extend(split(tri))
points={}
def add(p):
    k=(round(p[0],12),round(p[1],12))
    if k not in points: points[k]=len(points)
    return points[k]
indexed=[]
for tri in triangles:
    indexed.append([add(p) for p in tri])
offset=[list(p) for p in points]
absolute=[[p[0]+g['K'][0],p[1]+g['K'][1]] for p in offset]
area=sum(abs((offset[b][0]-offset[a][0])*(offset[c][1]-offset[a][1])-(offset[b][1]-offset[a][1])*(offset[c][0]-offset[a][0]))/2 for a,b,c in indexed)
max_edge=max(max(edge(offset[a],offset[b]),edge(offset[b],offset[c]),edge(offset[c],offset[a])) for a,b,c in indexed)
out={'source':'exact Voronoi pieces triangulated independently','coordinate_space':g['coordinate_space'],'K':g['K'],'Kp':g['Kp'],'reciprocal_basis':g['reciprocal_basis'],'area_bz':g['area_bz'],'area_voronoi_K':g['area_voronoi_K'],'expected_area_bz':g['expected_area_bz'],'expected_area_voronoi_K':g['expected_area_voronoi_K'],'pieces':g['pieces'],'points_offset_K':offset,'points_abs':absolute,'triangles':indexed,'area':area,'max_edge':max_edge,'limit':limit,'boundary_policy':g['tie_convention']}
(root/'.e7i1g_c1_exact_geometry.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'event':'c1_exact_geometry_complete','points':len(offset),'triangles':len(indexed),'area':area,'expected_area':g['area_voronoi_K'],'max_edge':max_edge},indent=2))
