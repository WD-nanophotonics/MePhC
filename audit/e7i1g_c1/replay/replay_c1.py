from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
fixture = json.loads((ROOT / "fixtures" / "c1_anchor_values.json").read_text())
coarse = fixture["coarse_flux_q"]
fine = fixture["fine_flux_q"]
three = fixture["three_point_flux_q"]
refined = fixture["refined_flux_q"]

def rel(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-300)

coarse_to_fine = [rel(a, b) for a, b in zip(coarse, fine)]
fine_to_refined = [rel(a, b) for a, b in zip(fine, refined)]
quadrature = [rel(a, b) for a, b in zip(fine, three)]
for actual, expected in zip(coarse_to_fine, fixture["expected_coarse_to_fine"]): assert abs(actual - expected) < 1e-12, (actual, expected)
for actual, expected in zip(fine_to_refined, fixture["expected_fine_to_refined"]): assert abs(actual - expected) < 1e-12, (actual, expected)
for actual, expected in zip(quadrature, fixture["expected_quadrature"]): assert abs(actual - expected) < 1e-12, (actual, expected)
assert max(fine_to_refined) <= 0.03
assert max(quadrature) <= 0.02
assert max(fixture["reported_hybrid_p90"]) <= 0.07
print(json.dumps({"status": "NUMERICALLY_EQUIVALENT", "coarse_to_fine": coarse_to_fine, "fine_to_refined": fine_to_refined, "quadrature": quadrature, "hybrid_p90_max": max(fixture["reported_hybrid_p90"])}, indent=2))
