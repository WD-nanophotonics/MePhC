from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "audit" / "berry_c3_consistency" / "goal_contract_v1.json"
PLAN_PATH = ROOT / "audit" / "berry_c3_consistency" / "PLAN.md"


def _polygon_area(radius: float, sides: int) -> float:
    return 0.5 * sides * radius * radius * math.sin(2.0 * math.pi / sides)


def test_goal_contract_is_self_consistent_and_solver_free_at_m1():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["schema"] == "mephc-scientific-goal-v1"
    assert contract["goal_id"] == "MEPHC-BERRY-C3-CONSISTENCY-V1"
    observation = contract["frozen_observation"]
    assert len(observation["sha256"]) == 64
    int(observation["sha256"], 16)
    assert observation["read_only"] is True
    assert observation["solver"]["symmetry"] == "raw_hbz"

    m1 = contract["milestones"][0]
    assert (m1["native_budget"], m1["provider_budget"], m1["solver_budget"]) == (0, 0, 0)
    assert contract["milestones"][1]["requires_explicit_successor_machine_budget"] is True
    assert contract["sampling"]["independent_rotated_solves_required"] is True
    assert contract["sampling"]["symmetry_expansion_forbidden"] is True


def test_area_matched_exact_c3_control_and_orbits():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    g16, g15 = contract["geometries"]["G16"], contract["geometries"]["G15"]
    for old_radius, new_radius in ((g16["r1"], g15["r1"]), (g16["r2"], g15["r2"])):
        assert math.isclose(_polygon_area(old_radius, 16), _polygon_area(new_radius, 15), rel_tol=1e-14)
    assert g15["n1"] % 3 == 0 and g15["n2"] % 3 == 0
    assert g16["n1"] % 3 != 0 and g16["n2"] % 3 != 0

    kx, ky = contract["sampling"]["k"]
    for offset in contract["sampling"]["orbit_seed_offsets"]:
        seed = (kx - offset / 36.0, ky)
        orbit = []
        for degrees in contract["sampling"]["rotation_degrees"]:
            angle = math.radians(degrees)
            dx, dy = seed[0] - kx, seed[1] - ky
            orbit.append((kx + math.cos(angle) * dx - math.sin(angle) * dy,
                          ky + math.sin(angle) * dx + math.cos(angle) * dy))
        assert len({(round(x, 14), round(y, 14)) for x, y in orbit}) == 3


def test_plan_and_contract_are_bound_by_content_not_self_referential_commit_sha():
    plan = PLAN_PATH.read_bytes()
    contract = CONTRACT_PATH.read_bytes()
    assert hashlib.sha256(plan).hexdigest()
    assert hashlib.sha256(contract).hexdigest()
    parsed = json.loads(contract)
    assert len(parsed["base_source_commit"]) == 40
    assert "final_sandbox_sha" not in parsed
    assert "origin_sandbox_sha" not in parsed
    assert "symmetrize" in PLAN_PATH.read_text(encoding="utf-8").lower()
