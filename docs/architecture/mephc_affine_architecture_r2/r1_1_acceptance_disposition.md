# R1.1 Acceptance Disposition

The R1.1 binding dispositions are accepted for R2 as follows:

1. SqrLatt's explicit `c4q` path remains a known case limitation and is not
   an R2 blocker.
2. R2 uses implementation commits first, followed by a separate evidence and
   closure commit.
3. No Gmail completion reply is required for acceptance.
4. The complete R1/R1.1 artifact directory is left byte-identical; R2 adds a
   sibling artifact directory.

The unchanged R1.1 tests remain in the final test set.  Its historical
validator also checks that the entire pre-R2 runtime tree is unchanged.  That
assertion necessarily fails after a legitimate R2 production migration, so
R2 records the preflight pass and validates the immutable R1/R1.1 artifact
and scientific-record subsets independently instead of weakening the old
validator.
