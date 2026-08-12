# Superseded R4 Findings

R4.1 records, without changing R4, that the previous closure had seven
defects: the final log was pre-seal; the receipt was pending at send; the
negative fixtures were mapping self-comparisons; Git/ref/topology/allowlist
gates were self-reported or absent; orchestration was incomplete and
developer-path dependent; and the final metadata commit contradicted the
recorded seal.

R4.1 replaces those claims with direct bundle checks, direct Git checks, real
subprocess fixtures, a portable orchestration record, and an external receipt
captured only after the new seal is pushed.
