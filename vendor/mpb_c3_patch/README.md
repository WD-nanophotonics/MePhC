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
