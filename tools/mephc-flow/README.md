# MePhC Thin Flow

Production is a four-command direct loop:

```text
status -> resume -> execute -> closeout
```

`mephc_flow.py` is the only coordinator. `scientific_job.py` owns generic
immutable datasets, and `wsl_native_exec.py` owns one foreground child process.
Everything under `archive/` is read-only historical code and is never imported.

There are no services, certificates, MCP servers, task-specific reconciliation
branches, or supervision gates in the production path.
