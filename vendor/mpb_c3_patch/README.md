# M64 isolated source boundary

M64R1 verifies the exact MPB 1.12.0 Build5 source accepted by M38. Static
inspection identifies the reciprocal-k and Maxwell operator source path, but
does not by itself prove the first runtime layer responsible for M63's
same-shell deformation. Therefore no unlocalized hunk is applied, no installed
backend is touched, and no patched scientific solve is run. The entrypoint
reports `R256_NATIVE_HOMOGENEOUS_DEFECT_NOT_LOCALIZED_NO_PATCH`.

Supervisor recovery subsequently found the exact Build5 Conda recipe and
package payload in the pinned environment cache.  The recipe binds the
official `mpb-1.12.0.tar.gz` release to SHA-256 `8d2b2062...eda4`; the
downloaded artifact is preserved under `source/`, and
`source_build5_provenance.json` records the complete package/source/library
identity.  Future work must build only from that artifact in an isolated
prefix and must not modify the installed backend.

The exact recovered Conda recipe is retained byte-for-byte under
`build5_recipe/`. `build_exact_build5.sh` reproduces its configure flags in a
fresh build directory and fresh prefix, verifies the source archive first,
and refuses the active Conda prefix.  An optional `MPB_PATCH_FILE` is applied
only inside that isolated source tree.  Every scientific child must still
record the resolved isolated library path and hash before using it.

M64R2 adds a trace-only dynamic localization boundary. Its entrypoint binds
the frozen M50/M60/M61R1/M63 evidence, records exact source/symbol hashes, and
uses only predeclared homogeneous probes. The instrumentation patch is
intentionally non-applicable: no scientific source hunk may be introduced
until an isolated Build5 runtime proves one unique earliest broken stage. The
installed backend is never modified, and a bounded no-patch result is valid
when that localization proof is unavailable.

M64R3 removes the downstream-name assumption: source functions, build inputs,
callgraph edges, and semantic stage candidates are discovered from the exact
tarball. The four native baseline probes are retained as an unpatched trace;
no MPB hunk is applied unless the isolated runtime proves one earliest stage.
