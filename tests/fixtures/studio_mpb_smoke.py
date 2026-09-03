"""One-point MPB smoke for the local Studio environment; writes no record."""

from mephc.studio.cases import default_profile
from mephc.studio.worker import run_request


profile = default_profile("triangular")
profile["project_root"] = "/home/icy/TriLatt"
profile["operations"]["frequency_at_k"].update(
    {"resolution": 8, "num_bands": 1, "kx": 0.0, "ky": 0.0}
)
result = run_request({"profile": profile, "operation": "frequency_at_k"})
assert result["status"] == "succeeded"
assert len(result["freqs"]) == 1
assert len(result["actual_freqs"]) == 1
print(result)
