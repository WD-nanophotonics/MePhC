#!/home/icy/miniconda3/envs/mp/bin/python
"""Minimal stdio MCP server exposing only typed MePhC runner operations."""
from __future__ import annotations
import contextlib, io, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import jobctl
TOOLS=[
 {"name":"mephc_capabilities","description":"Return canonical MePhC runner capabilities and active jobs.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
 {"name":"mephc_doctor","description":"Submit and wait for a canonical MePhC doctor job.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
 {"name":"mephc_resume","description":"Return active work or the unique safe continuation.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
 {"name":"mephc_change","description":"Atomically materialize, test, and commit exact UTF-8 files in MePhC.","inputSchema":{"type":"object","required":["expected_main","files","tests","commit_message"],"properties":{"expected_main":{"type":"string"},"files":{"type":"array","minItems":1,"items":{"type":"object","required":["path","expected_preimage_sha256","expected_postimage_sha256","content_utf8"],"properties":{"path":{"type":"string"},"expected_preimage_sha256":{"type":"string"},"expected_postimage_sha256":{"type":"string"},"content_utf8":{"type":"string"}},"additionalProperties":False}},"tests":{"type":"array","minItems":1,"items":{"type":"string"}},"commit_message":{"type":"string"}},"additionalProperties":False}},
 {"name":"mephc_submit","description":"Submit a typed non-change MePhC operation.","inputSchema":{"type":"object","required":["operation"],"properties":{"operation":{"type":"string","enum":["doctor","worktree","prelive","native","publish","courier"]},"arguments":{"type":"array","items":{"type":"string"}},"certificate_sha256":{"type":["string","null"]}},"additionalProperties":False}},
 {"name":"mephc_status","description":"Read one persisted job state.","inputSchema":{"type":"object","required":["job_id"],"properties":{"job_id":{"type":"string"}},"additionalProperties":False}},
 {"name":"mephc_wait","description":"Wait without killing the persistent job.","inputSchema":{"type":"object","required":["job_id"],"properties":{"job_id":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":4860}},"additionalProperties":False}},
 {"name":"mephc_recover","description":"Request the only state-approved recovery for an existing job.","inputSchema":{"type":"object","required":["job_id"],"properties":{"job_id":{"type":"string"}},"additionalProperties":False}}
]
def captured(call):
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream): result=call()
    return {"return_code":result if isinstance(result,int) else 0,"events":[json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]}
def invoke(name,args):
    if name=="mephc_capabilities": return jobctl.capabilities()
    if name=="mephc_resume": return jobctl.resume()
    if name=="mephc_doctor":
        directory=jobctl.submit("doctor",[],None); return captured(lambda:jobctl.wait(directory.name,120))
    if name=="mephc_change":
        directory=jobctl.submit_change(args); return {"job_id":directory.name,"state":"ready"}
    if name=="mephc_submit":
        directory=jobctl.submit(args["operation"],args.get("arguments",[]),args.get("certificate_sha256")); return {"job_id":directory.name,"state":"ready"}
    if name=="mephc_status": return jobctl.read_state(args["job_id"])
    if name=="mephc_wait": return captured(lambda:jobctl.wait(args["job_id"],args.get("timeout",4860)))
    if name=="mephc_recover":
        jobctl.request_recovery(args["job_id"]); return {"job_id":args["job_id"],"state":"recovery_requested"}
    raise ValueError(f"unknown tool: {name}")
def reply(identifier,result=None,error=None):
    value={"jsonrpc":"2.0","id":identifier}
    if error is not None: value["error"]={"code":-32000,"message":error}
    else: value["result"]=result
    print(json.dumps(value,separators=(",",":"),ensure_ascii=False),flush=True)
def main():
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line.lstrip("\ufeff")); method=request.get("method"); identifier=request.get("id")
            if method=="initialize": reply(identifier,{"protocolVersion":request.get("params",{}).get("protocolVersion","2025-03-26"),"capabilities":{"tools":{}},"serverInfo":{"name":"mephc-runner","version":"2.0.0"}})
            elif method=="ping": reply(identifier,{})
            elif method=="tools/list": reply(identifier,{"tools":TOOLS})
            elif method=="tools/call":
                params=request.get("params",{}); value=invoke(params.get("name"),params.get("arguments") or {}); reply(identifier,{"content":[{"type":"text","text":json.dumps(value,sort_keys=True,ensure_ascii=False)}],"isError":False})
            elif identifier is not None: reply(identifier,error=f"unsupported method: {method}")
        except Exception as exc:
            if request.get("id") is not None: reply(request.get("id"),error=f"{type(exc).__name__}: {exc}")
if __name__=="__main__": main()

