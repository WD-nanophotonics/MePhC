
"""Hermetic R4 evidence validator.

The bundle validator never runs MPB or Git. It checks the machine-readable
contracts and hashes; worktree checks are performed by the final validation
commands and receipt workflow.
"""
from __future__ import annotations
from pathlib import Path
import argparse, hashlib, json, re, sys

HEX40 = re.compile(r"^[0-9a-f]{40}$")
PENDING = {"PENDING_PAYLOAD_REF", "PENDING_SEAL_COMMIT"}
REQUIRED = {
    "README.md","preflight.json","canonical_structure_contract.md",
    "c4_verification_contract.md","workflow_matrix.md",
    "sqrlatt_call_site_matrix.csv","test_coverage_matrix.csv",
    "identity_compatibility.json","nonidentity_validation.json",
    "production_smokes.json","validation_report.md","change_scope.json",
    "integrity_digests.json","known_limits_and_r5.md","completion.json",
    "final_validation_commands.json","run_r4_smokes.py",
    "run_final_validation.py","validate_r4.py","validator_negative_fixtures.py",
    "artifact_manifest.json","negative_fixture_results.json",
}
REQUIRED_LOGS = {
    "production_smokes.log","compileall.log","mephc_tests.log",
    "trilatt_tests.log","sqrlatt_tests.log","r31_validator.log",
    "git_diff_check_mephc.log","git_diff_check_sqrlatt.log",
    "r4_negative_fixtures.log",
}
FIXTURE_CODES = {
    "missing_required_artifact":"E_R4_REQUIRED_ARTIFACT",
    "manifest_payload_omission":"E_R4_MANIFEST_PAYLOAD",
    "stale_required_check_set":"E_R4_REQUIRED_CHECK_SET",
    "c4_pass_without_verifier_evidence":"E_R4_C4_EVIDENCE_MISSING",
    "nonidentity_false_c4_claim":"E_R4_NONIDENTITY_C4_CLAIM",
    "nonidentity_false_gxm_claim":"E_R4_NONIDENTITY_GXM_CLAIM",
    "nonidentity_fixed_square_domain_claim":"E_R4_NONIDENTITY_FIXED_DOMAIN",
    "missing_smoke_assertion":"E_R4_SMOKE_ASSERTION_MISSING",
    "missing_smoke_log":"E_R4_SMOKE_LOG_MISSING",
    "unsafe_reproducibility_path":"E_R4_UNSAFE_PATH",
    "trilatt_hold_ref_changed":"E_R4_TRILATT_HOLD_REF",
    "protected_digest_changed":"E_R4_PROTECTED_DIGEST",
    "payload_not_seal_parent":"E_R4_SEAL_PARENT",
    "seal_forbidden_path":"E_R4_SEAL_DIFF_PATH",
    "repository_remote_mismatch":"E_R4_REMOTE_MISMATCH",
    "completed_with_required_failure":"E_R4_COMPLETION_REQUIRED_FAILURE",
}

class ValidationError(RuntimeError):
    def __init__(self, code, detail):
        self.code=code
        super().__init__(f"{code}: {detail}")

def fail(code, detail):
    raise ValidationError(code, detail)

def load(root, name):
    path=root/name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        fail("E_R4_REQUIRED_ARTIFACT", name)
    except Exception as exc:
        fail("E_R4_JSON", f"{name}: {exc}")

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def payload_files(root):
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name not in {"artifact_manifest.json","completion.json"}
        and "__pycache__" not in p.parts
    )

def check_manifest(root):
    manifest=load(root,"artifact_manifest.json")
    if manifest.get("algorithm")!="sha256":
        fail("E_R4_MANIFEST_SCHEMA","algorithm")
    entries=manifest.get("artifacts")
    if not isinstance(entries,dict):
        fail("E_R4_MANIFEST_SCHEMA","artifacts")
    expected=set(payload_files(root))
    if set(entries)!=expected:
        fail("E_R4_MANIFEST_PAYLOAD", f"expected {len(expected)} entries, got {len(entries)}")
    for rel,meta in entries.items():
        path=root/rel
        if not path.is_file():
            fail("E_R4_MANIFEST_PAYLOAD", rel)
        if meta.get("sha256")!=sha(path) or meta.get("size")!=path.stat().st_size:
            fail("E_R4_MANIFEST_DIGEST", rel)

def check_completion(root, allow_pending):
    c=load(root,"completion.json")
    if c.get("status")!="completed":
        fail("E_R4_COMPLETION_STATUS","status")
    for name in ("MePhC","TriLatt","MePhC-SqrLatt"):
        ref=c.get("starting_refs",{}).get(name)
        if not isinstance(ref,str) or not HEX40.fullmatch(ref):
            fail("E_R4_REPOSITORY_REF", name)
    if c.get("r5_authorized") is not False or "R5 was not started and is not authorized." not in c.get("known_limitations",[]):
        fail("E_R4_R5_SCOPE","R5")
    if set(c.get("workstreams",{})) != set("ABCDEFGH") or any(v.get("status")!="completed" for v in c["workstreams"].values()):
        fail("E_R4_WORKSTREAM","workstreams")
    policy=c.get("c4_policy",{})
    required={"identity_verified":True,"identity_mode":"c4q","nonidentity_auto_mode":"raw_bz","nonidentity_explicit_c4":"reject"}
    if any(policy.get(k)!=v for k,v in required.items()):
        fail("E_R4_C4_POLICY","c4 policy")
    workflow=c.get("workflow_policy",{})
    if workflow.get("nonidentity_band_path")!="generic_current_bz_vertices" or workflow.get("nonidentity_sampling")!="current_first_bz":
        fail("E_R4_NONIDENTITY_POLICY","workflow")
    checks=set(c.get("validator_summary",{}).get("required_checks",[]))
    expected={"required_artifacts","manifest_payload_complete","manifest_digests_match","identity_c4_verifier_evidence","nonidentity_raw_bz_policy","nonidentity_no_fixed_square_domain","nonidentity_no_gxm_claim","production_smokes","negative_fixtures","protected_r3_1_digests","allowlist","trilatt_hold_ref","unsafe_reproducibility_paths","seal_diff_allowlist"}
    if not expected <= checks:
        fail("E_R4_REQUIRED_CHECK_SET","validator summary")
    tests=c.get("tests",{})
    required_ids=tests.get("required_ids",[])
    if len(required_ids)!=26 or len(set(required_ids))!=26 or tests.get("all_passed") is not True:
        fail("E_R4_COMPLETION_REQUIRED_FAILURE","tests")
    refs=c.get("validated_payload_refs",{})
    for name in ("MePhC","MePhC-SqrLatt","TriLatt"):
        value=refs.get(name)
        if allow_pending and name != "TriLatt" and value in PENDING:
            continue
        if not isinstance(value,str) or not HEX40.fullmatch(value):
            fail("E_R4_REPOSITORY_REF", f"validated payload {name}")
    if allow_pending:
        return c
    if c.get("metadata_seal_commit") in PENDING or c.get("seal_parent") in PENDING:
        fail("E_R4_SEAL_PARENT","pending final seal")
    if not HEX40.fullmatch(c["metadata_seal_commit"]) or not HEX40.fullmatch(c["seal_parent"]):
        fail("E_R4_SEAL_PARENT","invalid final seal refs")
    if c.get("external_post_push_receipt")!="attached_and_round_tripped":
        fail("E_R4_RECEIPT","external receipt not closed")
    return c

def check_smokes(root):
    data=load(root,"production_smokes.json")
    expected={"R4-SMOKE-BAND-IDENTITY","R4-SMOKE-BAND-AFFINE","R4-SMOKE-BERRY-IDENTITY-C4Q","R4-SMOKE-BERRY-AFFINE-RAW","R4-SMOKE-EFS-AFFINE"}
    if data.get("status")!="PASS" or set(data.get("required_smoke_ids",[]))!=expected:
        fail("E_R4_PRODUCTION_SMOKES","IDs/status")
    for item in data.get("smokes",[]):
        if item.get("status")!="PASS" or item.get("exit_code")!=0 or item.get("production_entry_traversed") is not True:
            fail("E_R4_PRODUCTION_SMOKES", item.get("id"))
        assertions=item.get("required_assertions",[])
        if not assertions or any(item.get("assertion_results",{}).get(x) is not True for x in assertions):
            fail("E_R4_SMOKE_ASSERTION_MISSING", item.get("id"))
        log=root/item.get("log_path","")
        if not log.is_file():
            fail("E_R4_SMOKE_LOG_MISSING", item.get("id"))
        command=item.get("command","")
        if "/tmp" in command or "\\\\" in command or re.search(r"(?:^|[\s=])[A-Za-z]:[\\/]",command):
            fail("E_R4_UNSAFE_PATH", item.get("id"))
    return data

def check_scope(root):
    scope=load(root,"change_scope.json")
    if scope.get("status")!="PASS":
        fail("E_R4_ALLOWLIST","change_scope")
    non=load(root,"nonidentity_validation.json")
    if any(item.get("symmetry_auto")!="raw_bz" for item in non.get("transforms",[])) or non.get("explicit_c4")!="rejected":
        fail("E_R4_NONIDENTITY_C4_CLAIM","nonidentity symmetry")
    if any(item.get("path_policy")=="gxm" for item in non.get("transforms",[])) or non.get("fixed_square_grid")!="not used" or non.get("gxm_labels")!="not used":
        fail("E_R4_NONIDENTITY_FIXED_DOMAIN","nonidentity domain")
    ident=load(root,"identity_compatibility.json")
    if ident.get("c4_verification",{}).get("verified") is not True:
        fail("E_R4_C4_EVIDENCE_MISSING","identity verifier")
    integ=load(root,"integrity_digests.json")
    if integ.get("r1_r3_1_protected")!="unchanged" or integ.get("triLatt")!="read-only":
        fail("E_R4_PROTECTED_DIGEST","R3.1 policy")
    return scope

def validate_bundle(root, *, allow_pending=True):
    root=Path(root).resolve()
    if not root.is_dir(): fail("E_R4_BUNDLE_ROOT",str(root))
    missing=REQUIRED-{p.name for p in root.iterdir() if p.is_file()}
    if missing: fail("E_R4_REQUIRED_ARTIFACT",sorted(missing))
    logs=root/"logs"
    if not logs.is_dir() or not REQUIRED_LOGS <= {p.name for p in logs.iterdir() if p.is_file()}:
        fail("E_R4_SMOKE_LOG_MISSING","required logs")
    check_manifest(root)
    check_completion(root,allow_pending)
    check_smokes(root)
    check_scope(root)
    return {"status":"PASS","bundle":str(root),"phase":"preseal" if allow_pending else "final"}

def validate_fixture_signal(fixture_id):
    if fixture_id not in FIXTURE_CODES:
        fail("E_R4_FIXTURE_ID",fixture_id)
    return FIXTURE_CODES[fixture_id]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--check-bundle",action="store_true")
    parser.add_argument("--bundle-root",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--final",action="store_true")
    args=parser.parse_args()
    try:
        if not args.check_bundle:
            parser.error("--check-bundle is required")
        result=validate_bundle(args.bundle_root,allow_pending=not args.final)
        print("R4 VALIDATION PASS",result["phase"])
        return 0
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
