"""Explicit nominal/evaluated coordinate semantics."""
from sample_identity import exact_q

def _component_matches(evaluated,nominal,precision):
    return all(exact_q((evaluated[i],0))[0] in {exact_q((nominal[i],0))[0],exact_q((round(nominal[i],precision),0))[0]} for i in range(2))

def coordinate_mapping(nominal,evaluated):
    if exact_q(nominal)==exact_q(evaluated): return "EXACT"
    if _component_matches(evaluated,nominal,10): return "DECIMAL10_SERIALIZATION"
    if _component_matches(evaluated,nominal,12): return "DECIMAL12_SERIALIZATION"
    return "NONCANONICAL_MISMATCH"
