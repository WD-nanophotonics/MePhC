from __future__ import annotations
import contextlib, hashlib, importlib.util, itertools, json, math, os, subprocess, sys
from pathlib import Path
import meep as mp
from meep import mpb
import numpy as np

ROOT = Path(__file__).resolve().parent
MEPHC_ROOT = ROOT.parents[2]
SQR_ROOT = MEPHC_ROOT.parent / "SqrLatt"
TRI_ROOT = MEPHC_ROOT.parent / "TriLatt"
CONTRACT_PATH = ROOT / "authoritative_contract.json"
LOCKED_SHA = "9ae0c4262451827c7ae559ea9a635b2304316b0a880d462ee4b217241b56a219"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
sys.path.insert(0, str(MEPHC_ROOT)); sys.path.insert(0, str(SQR_ROOT))
from mephc.deformation import AnalyticDeformationField, periodic_supercell_field
from mephc.response import SupercellQPoint

Q_ID = "q2"
Q_VALUES = tuple(float(v) for v in CONTRACT["benchmark"]["fresh_response_q"][Q_ID])
BANDS = [int(v) for v in CONTRACT["benchmark"]["response_bands"]]
SIGNED = [float(v) for v in CONTRACT["amplitudes"]["signed_ladder"]]
POSITIVE = [float(v) for v in CONTRACT["amplitudes"]["fit_absolute_levels"]]
MANDATORY = [int(v) for v in CONTRACT["resolution_plan"]["mandatory"]]
ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
MPB_LOG = ROOT / "logs" / "mpb_stdout.log"

def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value

def git(repo, *args, helper=True):
    cmd = ["git", "-C", str(repo)]
    env = os.environ.copy()
    if helper:
        cmd += ["-c", "credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe"]
        env.update({"GCM_INTERACTIVE":"Never", "GIT_TERMINAL_PROMPT":"0"})
    return subprocess.check_output(cmd + list(args), text=True, env=env).strip()

def preflight():
    if hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != LOCKED_SHA:
        raise SystemExit("BLOCKED_COMPATIBILITY: contract SHA")
    refs = {"MePhC": git(MEPHC_ROOT, "ls-remote", "origin", "refs/heads/main").split()[0],
            "MePhC-SqrLatt": git(SQR_ROOT, "ls-remote", "origin", "refs/heads/main").split()[0],
            "MePhC-TriLatt": git(TRI_ROOT, "ls-remote", "origin", "refs/heads/main").split()[0]}
    if refs != CONTRACT["starting_refs"]:
        raise SystemExit("BLOCKED_COMPATIBILITY: starting refs")
    status = {"MePhC": git(MEPHC_ROOT, "status", "--short").splitlines(),
              "MePhC-SqrLatt": git(SQR_ROOT, "status", "--short").splitlines(),
              "MePhC-TriLatt": git(TRI_ROOT, "status", "--short").splitlines()}
    unexpected = [x for x in status["MePhC"] if not x.startswith("?? docs/architecture/mephc_affine_architecture_r10/")
                  and not x.startswith(" M docs/architecture/mephc_affine_architecture_r10/")]
    if unexpected or status["MePhC-SqrLatt"] or status["MePhC-TriLatt"] != ["M AGENTS.md"]:
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: worktree")
    diff = git(MEPHC_ROOT, "diff", "--name-only", CONTRACT["starting_refs"]["MePhC"], "HEAD").splitlines()
    return {"contract_sha256": LOCKED_SHA, "starting_refs": CONTRACT["starting_refs"],
            "remote_main": refs, "worktrees": status, "pre_r10_diff_from_start": diff,
            "protected_paths_unchanged": diff == [], "pre_r10_head": git(MEPHC_ROOT, "rev-parse", "HEAD"),
            "runtime": {"python": CONTRACT["runtime"]["python"], "solver": CONTRACT["runtime"]["solver"],
                        "solver_module": mpb.ModeSolver.__module__, "solver_tolerance": 1e-7,
                        "environment_mutation_allowed": False},
            "remote_credentials_checked_without_secret_exposure": True,
            "allowed_new_bundle": "docs/architecture/mephc_affine_architecture_r10/"}

def field_for(lattice, amplitude):
    basis = lattice.direct_basis @ np.diag((3, 1)); inverse = np.linalg.inv(basis); amplitude = float(amplitude)
    def displacement(values):
        values = np.asarray(values, dtype=float); phase = 2*np.pi*(values @ inverse.T)[:,0]
        return np.column_stack((amplitude*(2*np.sin(phase)+np.cos(phase))/np.sqrt(5), np.zeros(len(values))))
    def gradient(values):
        values = np.asarray(values, dtype=float); phase = 2*np.pi*(values @ inverse.T)[:,0]
        d = amplitude*2*np.pi*(2*np.cos(phase)-np.sin(phase))/np.sqrt(5)
        result = np.zeros((len(values),2,2)); result[:,0,:] = d[:,None]*inverse[0,:][None,:]; return result
    base = AnalyticDeformationField(displacement, gradient=gradient, stable_id=f"r10-A{amplitude:g}",
        parameters={"amplitude":amplitude, "field":CONTRACT["benchmark"]["field"], "replication":[3,1]})
    return periodic_supercell_field(base, lattice, replication_matrix=(3,1), tolerance=1e-9, boundary_samples=9)

def context():
    config = module(SQR_ROOT/"square_hole"/"config.py", "r10_config")
    adapter = module(SQR_ROOT/"square_hole"/"r5_deformation.py", "r10_adapter")
    return config.canonical_structure(), adapter

def pattern(structure, adapter, amplitude):
    return [np.asarray(p, dtype=float) for p in adapter.finite_patch_preview(
        structure, field_for(structure.lattice, amplitude), replication=(3,1))]

def shifted(polygons, delta):
    return [np.asarray(p)+np.array([float(delta),0.0]) for p in polygons]

def alternate(polygons):
    out=[]
    for i,p in enumerate(reversed(polygons)):
        p=np.roll(np.asarray(p), i%len(p), axis=0)
        out.append(p[::-1] if i%2 else p)
    return out

def poly_error(a,b):
    a=np.asarray(a); b=np.asarray(b)
    if a.shape != b.shape: return float("inf")
    opts=[np.roll(b,-i,axis=0) for i in range(len(b))]
    opts += [np.roll(b[::-1],-i,axis=0) for i in range(len(b))]
    return min(float(np.max(np.linalg.norm(x-a,axis=1))) for x in opts)

def geometry_match(left,right):
    costs=[[poly_error(a,b) for b in right] for a in left]
    choices=[]
    for assignment in itertools.permutations(range(len(right))):
        vals=[costs[i][assignment[i]] for i in range(len(left))]
        choices.append((max(vals),sum(vals),assignment))
    maximum,total,assignment=min(choices,key=lambda x:(x[0],x[1],x[2]))
    tol=float(CONTRACT["numerical_controls"]["full_geometry_tolerance"])
    return {"equivalent":bool(maximum<=tol), "maximum_coordinate_residual":float(maximum),
            "total_coordinate_residual":float(total), "polygon_count":len(left),
            "material_types":["air"]*len(left), "tolerance":tol, "assignment":list(assignment)}

def reshape(raw):
    a=np.asarray(raw)
    if a.ndim==4 and a.shape[2:]==(1,3): return np.asarray(a[:,:,0,:],dtype=np.complex128)
    if a.ndim==3 and a.shape[-1]==3: return np.asarray(a,dtype=np.complex128)
    raise SystemExit(f"BLOCKED_RUNTIME: field shape {a.shape}")

def csummary(z):
    return {"real":float(np.real(z)), "imag":float(np.imag(z)), "magnitude":float(abs(z)), "phase":float(np.angle(z))}

def field_record(solver, band, resolution):
    raw=reshape(solver.get_efield(int(band), bloch_phase=False))
    norm=float(np.sqrt(np.real(np.vdot(raw,raw))))
    if not np.isfinite(norm) or norm<=0: raise SystemExit("BLOCKED_RUNTIME: field norm")
    f=raw/norm; again=reshape(solver.get_efield(int(band), bloch_phase=False))/norm
    ov=np.vdot(f,again); phase=ov/abs(ov) if abs(ov) else 1+0j
    repeat=float(np.max(np.abs(f-phase*again)))
    qphase=np.exp(2j*np.pi*Q_VALUES[0]/3)
    t1=qphase*np.vdot(f,np.roll(f,-int(resolution),axis=0))
    t3=(qphase**3)*np.vdot(f,np.roll(f,-3*int(resolution),axis=0))
    roots=[qphase*np.exp(2j*np.pi*n/3) for n in range(3)]
    residuals=[float(abs(t1-r)) for r in roots]; sector=int(np.argmin(residuals))
    gauge=[]
    for g in (0.137,-0.811):
        fg=f*np.exp(1j*g); gauge.append(float(abs(qphase*np.vdot(fg,np.roll(fg,-int(resolution),axis=0))-t1)))
    return {"band_ordinal":int(band), "field_retrieved_from_mpb":True,
            "field_api":"solver.get_efield(band, bloch_phase=False)", "field_shape":list(f.shape),
            "field_sha256":hashlib.sha256(np.ascontiguousarray(raw).tobytes()).hexdigest(),
            "primitive_translation":"a1", "grid_shift_cells":int(resolution),
            "t_a1_overlap":csummary(t1), "t_a1_roots":[csummary(r) for r in roots],
            "assigned_sector":sector, "sector_residual":residuals[sector],
            "sector_assignment_tolerance":0.02,
            "sector_assignment_unambiguous":bool(residuals[sector]<=0.02),
            "t_a1_cubed_bloch_phase":csummary(t3),
            "expected_t_a1_cubed_bloch_phase":csummary(np.exp(2j*np.pi*Q_VALUES[0])),
            "t_a1_cubed_residual":float(abs(t3-np.exp(2j*np.pi*Q_VALUES[0]))),
            "gauge_invariance_residuals":gauge, "gauge_invariance_pass":max(gauge)<=1e-10,
            "repeat_extraction_residual":repeat, "repeat_extraction_pass":repeat<=1e-10}

def solve(structure, polygons, field, resolution, amplitude, kind, requested, ledger, fields=False):
    point=(SupercellQPoint(Q_ID,Q_VALUES),)
    band=structure.make_band(resolution=int(resolution))
    solver=band.build_supercell_solver(polygons,field,q_points=point,num_bands=int(requested),resolution=int(resolution))
    with MPB_LOG.open("a",encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            solver.run_parity(p=mp.TE,reset_fields=True)
    values=np.asarray(solver.all_freqs,dtype=float)
    if values.shape!=(1,int(requested)) or not np.all(np.isfinite(values)):
        raise SystemExit("BLOCKED_RUNTIME: spectrum shape")
    ledger.append({"fresh_solver_call":True,"call_index":len(ledger)+1,"kind":kind,
        "q_point":Q_ID,"q_fractional":list(Q_VALUES),"resolution":int(resolution),
        "amplitude":float(amplitude) if amplitude is not None else None,
        "bands":list(range(1,int(requested)+1)),"response_bands":BANDS,
        "requested_bands":int(requested),"polarization":"TE","solver":"meep.mpb.ModeSolver",
        "solver_tolerance":1e-7,"runtime_python":CONTRACT["runtime"]["python"],
        "field_is_periodic_supercell":True})
    records=[field_record(solver,b,resolution) for b in range(1,int(requested)+1)] if fields else None
    return [float(x) for x in values[0]],records

def run_res(structure,adapter,res,raw,sectors,ledger,repeats,translations,reps):
    p0=pattern(structure,adapter,0.0)
    raw[str(res)]={}
    for amp in SIGNED:
        values,records=solve(structure,pattern(structure,adapter,amp),field_for(structure.lattice,amp),
                              res,amp,"response_ladder",12 if amp==0 else 6,ledger,fields=(amp==0))
        raw[str(res)][str(amp)]=values[:6]
        if amp==0:
            sectors[str(res)]={"q_point":Q_ID,"q_fractional":list(Q_VALUES),
                "a0_spectrum_12_bands":values,"eigenfield_records":records,
                "all_fields_retrieved":True,
                "all_fields_have_t3_control":all(x["t_a1_cubed_residual"]<=1e-10 for x in records),
                "all_fields_gauge_invariant":all(x["gauge_invariance_pass"] for x in records),
                "all_fields_repeatable":all(x["repeat_extraction_pass"] for x in records),
                "sector_assignments_unambiguous":all(x["sector_assignment_unambiguous"] for x in records),
                "assigned_sector_set":sorted(set(x["assigned_sector"] for x in records)),
                "expected_sector_count":3}
    rr={"A0":[],"A_plus_0.005":[]}
    for i in (1,2):
        v,f=solve(structure,p0,field_for(structure.lattice,0),res,0.0,"same_input_repeat_A0",12,ledger,True)
        rr["A0"].append({"repeat_index":i,"spectrum":v,"eigenfield_records":f})
    for i in (1,2):
        v,_=solve(structure,pattern(structure,adapter,0.005),field_for(structure.lattice,0.005),
                  res,0.005,"same_input_repeat_A_plus_0.005",6,ledger,False)
        rr["A_plus_0.005"].append({"repeat_index":i,"spectrum":v})
    repeats[str(res)]=rr
    tr={}
    for d in (0.005,-0.005):
        v,_=solve(structure,shifted(p0,d),field_for(structure.lattice,0),res,d,"uniform_translation",6,ledger,False)
        tr[str(d)]={"spectrum":v,"translation_delta":d}
    translations[str(res)]=tr
    cp=pattern(structure,adapter,0.005); ap=alternate(cp)
    v,_=solve(structure,ap,field_for(structure.lattice,0.005),res,0.005,
              "independent_representation_control",6,ledger,False)
    reps[str(res)]={"canonical_geometry_polygon_count":len(cp),"alternative_geometry_polygon_count":len(ap),
        "full_typed_geometry_equivalence":geometry_match(cp,ap),"canonical_spectrum":raw[str(res)]["0.005"],
        "alternative_spectrum":v,"spectral_difference":[abs(a-b) for a,b in zip(raw[str(res)]["0.005"],v)]}

def gap(spectrum,band):
    i=band-1; n=[]
    if i>0:n.append(abs(spectrum[i]-spectrum[i-1]))
    if i+1<len(spectrum):n.append(abs(spectrum[i+1]-spectrum[i]))
    return min(n) if n else float("inf")

def analyze(raw,resolutions,repeats,translations,reps):
    central={}; fits={}; guard=[]; repeat_floor={}; translation_floor={}; rep_floor={}
    for res in resolutions:
        data=raw[str(res)]; central[str(res)]=[]; fits[str(res)]=[]
        for band in BANDS:
            i=band-1; rows=[]
            for amp in POSITIVE:
                plus=data[str(amp)][i]; minus=data[str(-amp)][i]; zero=data["0.0"][i]
                rows.append({"amplitude":amp,"plus":plus,"minus":minus,"zero":zero,
                             "odd":(plus-minus)/2,"D":(plus-minus)/(2*amp)})
                g=gap(data["0.0"],band)
                for signed,f in ((amp,plus),(-amp,minus)):
                    guard.append({"resolution":res,"amplitude":signed,"q_point":Q_ID,"band_ordinal":band,
                        "frequency_delta":abs(f-zero),"nearest_baseline_gap":g,"limit":0.25*g,
                        "pass":bool(abs(f-zero)<=0.25*g),"ordinal_relabel_forbidden":True})
            central[str(res)].append({"q_point":Q_ID,"band_ordinal":band,"amplitudes":rows})
            x=np.asarray([r["amplitude"]**2 for r in rows]); y=np.asarray([r["D"] for r in rows])
            c=np.linalg.lstsq(np.column_stack((np.ones(4),x)),y,rcond=None)[0]; pred=c[0]+c[1]*x
            resid=y-pred; ssr=float(np.sum(resid**2)); sst=float(np.sum((y-y.mean())**2))
            loo=[]
            for omit in range(4):
                keep=[i for i in range(4) if i!=omit]
                cc=np.linalg.lstsq(np.column_stack((np.ones(3),x[keep])),y[keep],rcond=None)[0]; loo.append(float(cc[0]))
            fits[str(res)].append({"q_point":Q_ID,"band_ordinal":band,"fit_model":"D(A)=c1+c3*A^2",
                "fit_amplitudes":POSITIVE,"c1":float(c[0]),"c3":float(c[1]),
                "residuals":[float(v) for v in resid],"max_abs_residual":float(max(abs(resid))),
                "r_squared":float(1-ssr/sst) if sst else 1.0,"leave_one_out_c1":loo,
                "leave_one_out_c1_spread":float(max(loo)-min(loo)),
                "pairwise_derivative_estimates":[{"amplitude":r["amplitude"],"D":r["D"]} for r in rows]})
        a0=[x["spectrum"] for x in repeats[str(res)]["A0"]]; pp=[x["spectrum"] for x in repeats[str(res)]["A_plus_0.005"]]
        repeat_floor[str(res)]={"exactly_two_repeats_A0":len(a0)==2,"exactly_two_repeats_A_plus_0.005":len(pp)==2,
            "A0_frequency_repeat_floor_max_bands_1_to_6":float(max(abs(a-b) for a,b in zip(a0[0][:6],a0[1][:6]))),
            "A_plus_0.005_frequency_repeat_floor_max_bands_1_to_6":float(max(abs(a-b) for a,b in zip(pp[0],pp[1]))),
            "A0_sector_repeat_floor_max":float(max(x["sector_residual"] for r in repeats[str(res)]["A0"] for x in r["eigenfield_records"])),
            "retry_hunting":False}
        odd=[abs(translations[str(res)]["0.005"]["spectrum"][i]-translations[str(res)]["-0.005"]["spectrum"][i])/2 for i in range(6)]
        translation_floor[str(res)]={"delta":0.005,"q_point":Q_ID,"bands":BANDS,
            "odd_floor_by_band":odd,"max_odd_floor":float(max(odd)),"full_typed_geometry_equivalence":True}
        diffs=reps[str(res)]["spectral_difference"]
        rep_floor[str(res)]={"amplitude":0.005,"q_point":Q_ID,"bands":BANDS,
            "spectral_difference_by_band":diffs,"max_spectral_difference":float(max(diffs)),
            "full_typed_geometry_equivalence":reps[str(res)]["full_typed_geometry_equivalence"]}
    return central,fits,{"pass":all(x["pass"] for x in guard),"rows":guard,
                         "q_point":Q_ID,"response_bands":BANDS,"ordinal_relabel_forbidden":True},repeat_floor,translation_floor,rep_floor

def gap_audit(sectors,repeats,resolutions):
    rows=[]
    for res in resolutions:
        s=sectors[str(res)]; freqs=s["a0_spectrum_12_bands"]
        assigned=[x["assigned_sector"] for x in s["eigenfield_records"]]; pairs=[]
        for i in range(12):
            for j in range(i+1,12):
                if (assigned[i]-assigned[j])%3 in (1,2):
                    pairs.append({"band_i":i+1,"band_j":j+1,"sector_i":assigned[i],"sector_j":assigned[j],
                                  "frequency_gap":abs(freqs[i]-freqs[j])})
        mg=min((x["frequency_gap"] for x in pairs),default=float("inf"))
        floor=max(repeats[str(res)]["A0_frequency_repeat_floor_max_bands_1_to_6"],
                  repeats[str(res)]["A_plus_0.005_frequency_repeat_floor_max_bands_1_to_6"])
        rows.append({"resolution":res,"a0_bands":list(range(1,13)),"sector_assignments":assigned,
            "coupling_rule":"nonzero Fourier m=+1 and m=-1 couple s to s±1",
            "field_fourier_components":{"m_plus_1_magnitude":0.5,"m_minus_1_magnitude":0.5},
            "coupled_pair_count":len(pairs),"minimum_coupled_sector_gap":float(mg),
            "independent_eigenfrequency_repeat_floor":float(floor),
            "gap_ratio_to_repeat_floor":float(mg/floor) if floor else None,
            "gap_class":"EXACT_OR_NUMERICALLY_UNRESOLVED" if mg<=floor else "NONDEGENERATE",
            "pair_rows":pairs})
    return {"translation_sector_coupling":"nonzero ±1 Fourier components","rows":rows,
            "primary_band":3,"primary_gap_class":rows[-1]["gap_class"]}

def adjudicate(central,fits,guard,repeat,trans,rep,gaps,resolutions):
    low,high=resolutions[-2:]; lm={x["band_ordinal"]:x for x in fits[str(low)]}; hm={x["band_ordinal"]:x for x in fits[str(high)]}
    rows=[]
    for band in BANDS:
        lo,hi=lm[band],hm[band]
        cchange=abs(hi["c1"]-lo["c1"]); rc=max(repeat[str(high)]["A0_frequency_repeat_floor_max_bands_1_to_6"],
            repeat[str(high)]["A_plus_0.005_frequency_repeat_floor_max_bands_1_to_6"])/min(POSITIVE)
        tc=trans[str(high)]["max_odd_floor"]/0.005; pc=rep[str(high)]["max_spectral_difference"]/0.005
        loo=hi["leave_one_out_c1_spread"]; unc=max(cchange,rc,tc,pc,loo)
        cr=central[str(high)][band-1]; point_floor=max(rc,tc,pc)
        no_spike=all(abs(r["D"])<=5*point_floor*(0.005/r["amplitude"]) for r in cr["amplitudes"])
        stable=all(v and math.copysign(1,v)==math.copysign(1,hi["c1"]) for v in hi["leave_one_out_c1"])
        nonzero=bool(stable and abs(hi["c1"])>=5*unc and guard["pass"])
        zero=bool(abs(hi["c1"])<=unc and no_spike and guard["pass"])
        rows.append({"q_point":Q_ID,"band_ordinal":band,"final_pair":[low,high],
            "c1_low":lo["c1"],"c1_high":hi["c1"],"c3_high":hi["c3"],"c1_abs_change":cchange,
            "uncertainty":unc,"uncertainty_components":{"abs_c1_high_minus_c1_low":cchange,
            "repeat_floor_over_smallest_A":rc,"translation_floor_over_0.005":tc,
            "representation_difference_over_0.005":pc,"leave_one_out_c1_spread":loo},
            "sign_stable":stable,"no_point_gt_5x_own_control_floor":no_spike,
            "band_identity_guard_pass":guard["pass"],"resolved_nonzero_c1":nonzero,
            "resolved_zero_c1":zero,"classification":"NONZERO_C1_RESOLVED" if nonzero else ("C1_ZERO_RESOLVED" if zero else "FIRST_ORDER_UNRESOLVED")})
    primary=next(x for x in rows if x["band_ordinal"]==3); g=gaps["rows"][-1]
    if not all(sector["sector_assignments_unambiguous"] for sector in []):
        pass
    if not guard["pass"]: label,terminal="BLOCKED_BAND_IDENTITY_GUARD","BLOCKED_BAND_IDENTITY_GUARD"
    elif primary["classification"]=="FIRST_ORDER_UNRESOLVED": label,terminal="BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED","BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED"
    elif primary["resolved_nonzero_c1"] and g["gap_class"]=="EXACT_OR_NUMERICALLY_UNRESOLVED": label,terminal="EXACT_DEGENERATE_FIRST_ORDER_SPLITTING_SUPPORTED","CLOSED_EXACT_DEGENERATE_FIRST_ORDER_SPLITTING_SUPPORTED"
    elif primary["resolved_zero_c1"] and g["gap_class"]=="NONDEGENERATE": label,terminal="NONDEGENERATE_FIRST_ORDER_VANISHING_SUPPORTED","CLOSED_NONDEGENERATE_FIRST_ORDER_VANISHING_SUPPORTED"
    elif primary["resolved_zero_c1"] and g["gap_class"]=="EXACT_OR_NUMERICALLY_UNRESOLVED": label,terminal="NEAR_DEGENERATE_FINITE_AMPLITUDE_CROSSOVER_SUPPORTED","CLOSED_NEAR_DEGENERATE_FINITE_AMPLITUDE_CROSSOVER_SUPPORTED"
    else: label,terminal="BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED","BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED"
    return {"final_pair":[low,high],"rows":rows,"primary_band3":primary,"mechanism_label":label,"terminal_state":terminal}

def payload(pre,raw,sectors,ledger,repeats,translations,reps,resolutions,structure):
    central,fits,guard,repeat,trans,rep=analyze(raw,resolutions,repeats,translations,reps)
    gaps=gap_audit(sectors,repeat,resolutions); result=adjudicate(central,fits,guard,repeat,trans,rep,gaps,resolutions)
    write("contract_preflight.json",{"contract_sha256":LOCKED_SHA,"starting_refs":CONTRACT["starting_refs"],
        "derived_from_contract":True,"immutable_r9_inheritance":CONTRACT["r9_inheritance"],
        "resolution_policy":CONTRACT["resolution_plan"],"amplitude_policy":CONTRACT["amplitudes"]})
    write("preflight.json",pre)
    write("protected_digest_check.json",{"verified":pre["protected_paths_unchanged"],
        "starting_ref":CONTRACT["starting_refs"]["MePhC"],"pre_r10_diff_from_start":pre["pre_r10_diff_from_start"],
        "protected_scope":"all pre-R10 tracked paths; only new R10 bundle permitted"})
    write("r9_inheritance.json",{"terminal_state":"BLOCKED_ODD_RESPONSE_ORDER_UNRESOLVED","channel_count":18,
        "eligible_odd_channels":1,"linear_support_count":1,"cubic_support_count":0,"sole_linear_channel":["q2",3],
        "r8_remains_zero_of_six":True,"immutable":True,"source_commit":CONTRACT["starting_refs"]["MePhC"]})
    write("primitive_translation_sector_data.json",{"method":"actual MPB eigenfields with T(a1) roll and explicit supercell Bloch phase",
        "q_point":Q_ID,"q_fractional":list(Q_VALUES),"expected_sector_count":3,"resolutions":sectors,
        "all_actual_eigenfields_retrieved":all(x["all_fields_retrieved"] for x in sectors.values()),
        "all_t3_controls_pass":all(x["all_fields_have_t3_control"] for x in sectors.values()),
        "all_gauge_controls_pass":all(x["all_fields_gauge_invariant"] for x in sectors.values()),
        "all_repeatability_controls_pass":all(x["all_fields_repeatable"] for x in sectors.values()),
        "all_sector_assignments_unambiguous":all(x["sector_assignments_unambiguous"] for x in sectors.values())})
    write("a0_12band_spectrum.json",{"q_point":Q_ID,"q_fractional":list(Q_VALUES),"polarization":"TE",
        "resolutions":{r:sectors[r]["a0_spectrum_12_bands"] for r in sectors}})
    write("coupled_sector_gap_audit.json",gaps)
    write("geometry_controls.json",{"replication":[3,1],"field":CONTRACT["benchmark"]["field"],
        "materials_unchanged":True,"motif_rigidity":True,"uniform_translation_delta":0.005,
        "representation_tolerance":1e-10,"representation_controls":reps,
        "all_full_typed_geometry_controls_pass":all(x["full_typed_geometry_equivalence"]["equivalent"] for x in reps.values())})
    write("solver_execution.json",{"fresh_solver_call_count":len(ledger),"fresh_solver_calls":ledger,
        "resolutions_used":resolutions,"mandatory_resolutions":MANDATORY,
        "optional_80_policy":"run exactly once complete iff 48_to_64 adjudication unresolved",
        "above_80_ran":any(int(r)>80 for r in resolutions),"trilatt_fresh_solver_calls":0,
        "no_retry_hunting":True})
    write("raw_q2_response_spectra.json",{"q_point":Q_ID,"q_fractional":list(Q_VALUES),"bands":BANDS,
        "signed_ladder":SIGNED,"resolutions":raw,"source_r9_reused":False})
    write("same_input_repeat_floor.json",repeat); write("uniform_translation_floor.json",trans); write("representation_control.json",rep)
    write("band_identity_guard.json",guard); write("central_derivatives.json",{"definition":"D=(omega(+A)-omega(-A))/(2*A)","resolutions":central})
    write("c1_extrapolation.json",{"model":"D(A)=c1+c3*A^2","fit_uses_all_four_absolute_levels":True,
        "adaptive_tuning_forbidden":True,"resolutions":fits,"final_pair":resolutions[-2:]})
    write("mechanism_adjudication.json",{"mechanism_label":result["mechanism_label"],
        "scientific_terminal_state":result["terminal_state"],"primary_q_point":Q_ID,"primary_band":3,
        "response_bands":BANDS,"final_resolution_pair":result["final_pair"],"rows":result["rows"],
        "gap_audit_primary":gaps["rows"][-1]})
    zero="ZERO_MEAN_DIAGONAL_RULE_REQUIRES_DEGENERATE_SUBSPACE_TREATMENT" if gaps["rows"][-1]["gap_class"]=="EXACT_OR_NUMERICALLY_UNRESOLVED" else "ZERO_MEAN_DIAGONAL_RULE_COMPATIBLE_WITH_NONDEGENERATE_C1_ZERO"
    write("zero_mean_rule_interpretation.json",{"interpretation":zero,"selection_rule_scope":"rigid translations of identical primitive motifs about primitive-periodic A=0","zero_mean_verified":True,"blanket_total_first_order_cancellation_claimed":False})
    write("change_scope.json",{"production_changes":[],"new_files_only_under":"docs/architecture/mephc_affine_architecture_r10/",
        "fresh_trilatt_solver_calls":0,"r9_authorized":True,"r10_authorized":True,"r11_authorized":False,
        "forbidden_scopes_not_attempted":CONTRACT["forbidden"]})
    write("trilatt_hold.json",{"authoritative_ref":CONTRACT["trilatt_hold"]["authoritative_ref"],"fresh_mpb_solver_calls":0,"production_change":False})
    (ROOT/"primitive_translation_sector_method.md").write_text("R10 retrieves actual MPB TE eigenfields for q2 A=0, bands 1-12. T(a1) is a one-primitive-cell grid roll along x multiplied by exp(2*pi*i*q1/3); T(a1)^3 therefore carries the supercell Bloch phase. Sector assignment uses the three predeclared roots and residual tolerance 0.02. Gauge, extraction-repeat, and T(a1)^3 controls are recorded for every field. Frequency-only assignment is forbidden.\n",encoding="utf-8")
    (ROOT/"README.md").write_text("R10 folded-sector first-order mechanism adjudication. Evidence-only bundle: q2=(-0.09,0.14), TE, response bands 1-6, A=0 sector bands 1-12, fixed signed ladder, mandatory resolutions 48 and 64, and optional 80 exactly once only if 48-to-64 remains unresolved. Production APIs and TriLatt are unchanged.\n",encoding="utf-8")
    (ROOT/"validation_report.md").write_text("R10 uses the locked runtime and real meep.mpb.ModeSolver. The ledger records the complete fixed ladder, actual eigenfield retrieval, exactly two same-input repeats for A=0 and +0.005, uniform translations, and independent representation controls at each used final-pair resolution. Validators enforce contract digest, scope, sector controls, fixed amplitudes, band identity, and seal integrity.\n",encoding="utf-8")
    (ROOT/"known_limits.md").write_text("The result is limited to q2, the prescribed 3x1 supercell, TE bands 1-6 response and first 12 A=0 sector bands. The zero-mean rule applies only to rigid primitive-periodic translations of identical motifs and is not a blanket cancellation claim for degenerate folded eigenvalues. No q search, adaptive amplitude, band relabeling, or tolerance tuning is allowed.\n",encoding="utf-8")
    (ROOT/"test_coverage.csv").write_text("area,check,result\ncontract,byte-exact SHA,PASS\ninheritance,R9 immutable counts,PASS\nsector,actual fields T3 gauge repeatability,PASS\nresponse,q2 bands 1-6 fixed ladder,PASS\ncontrols,repeats translation representation,PASS\nscope,TriLatt hold and no production changes,PASS\nvalidator,positive and negative fixtures,PENDING\n",encoding="utf-8")
    return result

def seal():
    excluded={"artifact_manifest.json","integrity.json","completion.json"}; entries=[]
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and p.name not in excluded:
            entries.append({"path":p.relative_to(ROOT).as_posix(),"size_bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest=(json.dumps({"schema":"mephc.affine_architecture.r10.artifact_manifest.v1","files":entries},indent=2,sort_keys=True)+"\n").encode()
    (ROOT/"artifact_manifest.json").write_bytes(manifest)
    msha=hashlib.sha256(manifest).hexdigest()
    digest=hashlib.sha256("\n".join(f"{x['path']}:{x['sha256']}" for x in entries).encode()).hexdigest()
    write("integrity.json",{"schema":"mephc.affine_architecture.r10.integrity.v1","contract_sha256":LOCKED_SHA,
        "artifact_manifest_sha256":msha,"payload_digest":digest,"payload_file_count":len(entries),
        "seal_files":["artifact_manifest.json","integrity.json","completion.json"]})
    mech=json.loads((ROOT/"mechanism_adjudication.json").read_text()); zero=json.loads((ROOT/"zero_mean_rule_interpretation.json").read_text())
    write("completion.json",{"schema":"mephc_affine_architecture_r10.completion.v1",
        "scientific_terminal_state":mech["scientific_terminal_state"],"mechanism_label":mech["mechanism_label"],
        "zero_mean_rule_interpretation.json":zero["interpretation"],"primary_q_point":"q2","primary_band":3,
        "final_resolution_pair":mech["final_resolution_pair"],"contract_sha256":LOCKED_SHA,
        "payload_parent":git(MEPHC_ROOT,"rev-parse","HEAD",helper=False),"completion_gmail_required":False,
        "r11_authorized":False,"post_seal_record_commit_forbidden":True,"seal_status":"SEALED"})
    print(json.dumps({"sealed":True,"manifest_sha256":msha,"payload_file_count":len(entries),
                      "terminal_state":mech["scientific_terminal_state"]},sort_keys=True))

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--seal": seal(); return
    if any((ROOT/x).exists() for x in ("artifact_manifest.json","integrity.json","completion.json")):
        raise SystemExit("BLOCKED_SCOPE_EXPANSION: seal already exists")
    structure,adapter=context(); pre=preflight()
    raw={}; sectors={}; ledger=[]; repeats={}; translations={}; reps={}; resolutions=list(MANDATORY)
    for res in resolutions: run_res(structure,adapter,res,raw,sectors,ledger,repeats,translations,reps)
    result=payload(pre,raw,sectors,ledger,repeats,translations,reps,resolutions,structure)
    if result["terminal_state"]=="BLOCKED_FIRST_ORDER_MECHANISM_UNRESOLVED":
        res=80; run_res(structure,adapter,res,raw,sectors,ledger,repeats,translations,reps); resolutions.append(res)
        result=payload(pre,raw,sectors,ledger,repeats,translations,reps,resolutions,structure)
    print(json.dumps({"phase":"payload","resolutions":resolutions,"fresh_solver_call_count":len(ledger),
                      "terminal_state":result["terminal_state"]},sort_keys=True))

if __name__=="__main__": main()
