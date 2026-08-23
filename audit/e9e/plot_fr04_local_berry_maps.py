"""E9E.D audit-only context/core Berry map plots."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]

def plot(result_path, output_dir):
    import matplotlib.pyplot as plt
    result=json.loads(Path(result_path).read_text(encoding="utf-8-sig"))
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    paths=[]
    for grid_name, shape, extent in (("context",(13,13),(-1/6,1/6,-1/6,1/6)),("core",(9,9),(-1/36,1/36,-1/36,1/36))):
        values={band:np.full(shape,np.nan) for band in (1,2,3)}
        rows=[row for row in result["numerical_map"] if row["grid_name"]==grid_name]
        half=(shape[0]-1)//2
        for row in rows:
            for band in (1,2,3):
                value=row["bands"][band-1]["Omega_over_a2"]
                if value is not None: values[band][row["grid_j"]+half,row["grid_i"]+half]=value
        for band in (1,2,3):
            fig,ax=plt.subplots(figsize=(6,5),constrained_layout=True)
            image=ax.imshow(values[band],origin="lower",extent=extent,aspect="equal",cmap="coolwarm")
            ax.set_title(f"E9E.D f_r=0.4 Berry curvature band {band} ({grid_name})")
            ax.set_xlabel("q_x offset from public K-prime")
            ax.set_ylabel("q_y offset from public K-prime")
            fig.colorbar(image,ax=ax,label="Omega / a^2")
            path=out/f"fr04_band{band}_{grid_name}_map.png"; fig.savefig(path,dpi=150); plt.close(fig); paths.append(str(path))
    return paths

if __name__=="__main__":
    result=Path(sys.argv[sys.argv.index("--result")+1]) if "--result" in sys.argv else ROOT/"audit/e9e/d_result.json"
    out=Path(sys.argv[sys.argv.index("--output-dir")+1]) if "--output-dir" in sys.argv else ROOT/"audit/e9e/d_plots"
    print(json.dumps({"plots":plot(result,out)},sort_keys=True))
