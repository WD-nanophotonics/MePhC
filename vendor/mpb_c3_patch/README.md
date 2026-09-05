# M64 isolated source boundary

M64 requires the exact MPB 1.12.0 unpatched source accepted by M38. No such
source artifact is available in this workspace, so no hunk is applied, no
isolated build is attempted, and the installed Meep/MPB environment is not
modified. The Thin Flow entrypoint reports `R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH`
with zero patched scientific solves and requests supervisor reconciliation.

Supervisor recovery subsequently found the exact Build5 Conda recipe and
package payload in the pinned environment cache.  The recipe binds the
official `mpb-1.12.0.tar.gz` release to SHA-256 `8d2b2062...eda4`; the
downloaded artifact is preserved under `source/`, and
`source_build5_provenance.json` records the complete package/source/library
identity.  Future work must build only from that artifact in an isolated
prefix and must not modify the installed backend.
