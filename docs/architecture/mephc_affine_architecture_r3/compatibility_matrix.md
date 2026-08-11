# Compatibility Matrix

| surface | identity | nonidentity |
|---|---|---|
| geometry ID | unchanged | includes deformation token |
| old records | readable and not rewritten | never falsely matched to identity records |
| k-space legacy helpers | available | guarded with a clear capability error |
| `Band.default_path` | legacy path | generic current-BZ path |
| C3/HBZ expansion | available when eligible | rejected rather than silently reused |

No scientific records, images, diagnostics, or SqrLatt files were modified.
