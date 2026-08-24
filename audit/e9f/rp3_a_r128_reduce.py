from pathlib import Path
import copy, hashlib, json
from audit.e9f import c3_c5_c1_postprocess as c1

ROOT = Path("/home/icy/MePhC/.c3-c5-c1-live4")
RUNTIME = Path("/home/icy/MePhC/.rp3-a-r128-runtime-20260825-run2")


def build_trace(root=ROOT, runtime=RUNTIME):
    result = json.loads((runtime / "rp3_a_r128_result.json").read_text())
    old = json.loads((root / "audit/e9f/c3_c5_c1_c1_postprocess.json").read_text())["complete_entries"]
    old_map = {(x["source_sample_id"], int(x["resolution"]), x["stencil"]): x for x in old}
    rows, spectral, entries = [], [], []
    for payload in result["payloads"]:
        sample = payload["source_sample_id"]
        for stencil in ("1/72", "1/144"):
            old64, old96 = old_map[(sample, 64, stencil)], old_map[(sample, 96, stencil)]
            source_entry = copy.deepcopy(payload["stencils"][stencil])
            association = source_entry["association"]
            for edge in association["edges"]:
                edge["assignment"] = c1.derive_positional_assignment(edge, association["candidate_window_zero_based"])
            points = [payload["center"], *source_entry["vertices"]]
            entries.append({"source_sample_id": sample, "source_sample_index": payload["source_sample_index"], "logical_sample_index": payload["logical_sample_index"], "worker_id": payload["worker_id"], "resolution": 128, "stencil": stencil, "CENTER_L0": payload["center"]["L0"], "VERTEX_L0": [x["L0"] for x in source_entry["vertices"]], "association": association, "BAND2": source_entry["BAND2_PHYSICAL_BRANCH_SHADOW"], "BAND3": source_entry["BAND3_PHYSICAL_BRANCH_SHADOW"], "L2": source_entry["L2_RANK2"], "L3": source_entry.get("L3"), "H_MAX": {"full6_offdiag": max(x["H_GATE"]["max_offdiag"] for x in points), "selected_pair_offdiag": max(x["H_GATE"]["selected_pair_offdiag"] for x in points), "normalization_error": max(x["H_GATE"]["max_normalization_error"] for x in points)}, "replay_policy": "NOT_APPLICABLE_R128_ORIGINAL_RP2_HAS_NO_R128_KEY"})
            for branch, key in (("band2", "BAND2"), ("band3", "BAND3")):
                r64, r96 = old64[key]["OMEGA_RANK1_SHADOW"], old96[key]["OMEGA_RANK1_SHADOW"]
                r128 = source_entry[key + "_PHYSICAL_BRANCH_SHADOW"]["OMEGA_RANK1_SHADOW"]
                d1, d2 = r96 - r64, r128 - r96
                rows.append({"source_sample_id": sample, "branch": branch, "stencil": stencil, "omega_R64": r64, "omega_R96": r96, "omega_R128": r128, "delta_R64_to_R96_signed": d1, "delta_R64_to_R96_abs": abs(d1), "delta_R96_to_R128_signed": d2, "delta_R96_to_R128_abs": abs(d2), "contraction_ratio_diagnostic_only": None if d1 == 0 else abs(d2) / abs(d1)})
        old_l0 = old_map[(sample, 96, "1/72")]["CENTER_L0"]
        new_l0 = payload["center"]["L0"]
        spectral.append({"source_sample_id": sample, "center_L0_R96": old_l0, "center_L0_R128": new_l0, "delta_L0_R96_to_R128": {k: new_l0[k] - old_l0[k] for k in ("lower_external_gap", "internal_pair_gap", "upper_external_gap")}, "center_frequency_R128": payload["center"]["RAW_FREQUENCIES_ALL6"], "R128_REPLAY_POLICY": "NOT_APPLICABLE_R128"})
    measurements = [{"worker_id": m["worker_id"], "pid": m["pid"], "return_code": m["return_code"], "direct_pid_gone": m["direct_pid_gone"], "orphan_count": m["orphan_count"], "elapsed_seconds": m["elapsed_seconds"], "payload_file_sha256": m["payload_file_sha256"], "payload_body_sha256": m["payload_body_sha256"]} for m in result["measurements"]]
    return {"schema": "mephc_e9f_c1_rp3_a_r128_compact_trace_v2", "work_order_id": result["work_order_id"], "execution_sha": result["execution_sha"], "source_science_execution_sha": "02b8fc343b3dd786769c42cfa8e44bd57add482d", "raw_runtime_root": str(runtime), "raw_result_sha256": hashlib.sha256((runtime / "rp3_a_r128_result.json").read_bytes()).hexdigest(), "raw_manifest_sha256": hashlib.sha256((runtime / "rp3_a_r128_manifest.json").read_bytes()).hexdigest(), "raw_checkpoint_sha256": hashlib.sha256((runtime / "matrix_checkpoint.json").read_bytes()).hexdigest(), "authorized_native_solve_count": 54, "actual_native_solve_count": result["actual_native_solve_count"], "worker_count": 6, "entry_count": 12, "replay_policy": result["replay_policy"], "convergence_rows": rows, "spectral_rows": spectral, "measurements": measurements, "entries": entries, "no_convergence_verdict": True, "diagnostic_only": True, "reducer_admissible": False}


if __name__ == "__main__":
    out = ROOT / "audit/e9f/rp3_a_r128_compact_trace.json"
    out.write_text(json.dumps(build_trace(), indent=2, sort_keys=True, allow_nan=False) + chr(10))
    print(hashlib.sha256(out.read_bytes()).hexdigest())
