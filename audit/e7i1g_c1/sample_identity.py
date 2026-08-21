"""Canonical physical identity for reusable Berry samples."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FIELDS = ("q", "valley", "radius_a", "radius_b", "resolution", "h", "representation", "plaquette", "geometry", "selected_bands", "rank")


def canonical_q(value):
    return (round(float(value[0]), 10), round(float(value[1]), 10))


def _geometry(record):
    return record.get("geometry") or record.get("provenance", {}).get("geometry")


def _bands(record):
    return tuple(int(value) for value in record.get("selected_bands_one_based", record.get("selected_bands", ())))


@dataclass(frozen=True)
class SampleIdentity:
    q: tuple[float, float]
    valley: str
    radius_a: float
    radius_b: float
    resolution: int
    h: float
    representation: str
    plaquette: str
    geometry: str
    selected_bands: tuple[int, ...]
    rank: int

    def as_dict(self) -> dict[str, Any]:
        return {"q": list(self.q), "valley": self.valley, "radius_a": self.radius_a, "radius_b": self.radius_b, "resolution": self.resolution, "h": self.h, "representation": self.representation, "plaquette": self.plaquette, "geometry": self.geometry, "selected_bands": list(self.selected_bands), "rank": self.rank}

    def canonical_key(self) -> tuple:
        return (self.q, self.valley, self.radius_a, self.radius_b, self.resolution, self.h, self.representation, self.plaquette, self.geometry, self.selected_bands, self.rank)


def identity_from_result(result: dict, q=None) -> SampleIdentity:
    target = q if q is not None else result.get("target_q", result.get("q"))
    radii = result.get("radii", (None, None))
    if target is None or len(radii) != 2:
        raise ValueError("sample lacks q/radii identity")
    return SampleIdentity(canonical_q(target), str(result.get("valley")), float(radii[0]), float(radii[1]), int(result.get("resolution")), float(result.get("h")), str(result.get("representation")), str(result.get("plaquette")), str(_geometry(result)), _bands(result), int(result.get("rank")))


def expected_identity(q) -> SampleIdentity:
    return SampleIdentity(canonical_q(q), "K", 0.15, 0.25, 64, 0.001, "mpb_live_energy_eh_v1", "CENTERED_CCW", "d0500-minus-sealed-honeycomb", (1, 2), 1)


def mismatch_classes(expected: SampleIdentity, actual: SampleIdentity | None) -> list[str]:
    if actual is None:
        return ["MISSING_REQUIRED_PROVENANCE"]
    result = []
    if actual.q != expected.q:
        result.append("WRONG_Q")
    if actual.valley != expected.valley:
        result.append("WRONG_VALLEY")
    if (actual.radius_a, actual.radius_b) != (expected.radius_a, expected.radius_b):
        result.append("WRONG_DOMAIN")
    if actual.resolution != expected.resolution:
        result.append("WRONG_RESOLUTION")
    if actual.h != expected.h:
        result.append("WRONG_H")
    if actual.representation != expected.representation:
        result.append("WRONG_REPRESENTATION")
    if actual.plaquette != expected.plaquette:
        result.append("WRONG_PLAQUETTE")
    if actual.geometry != expected.geometry:
        result.append("WRONG_GEOMETRY")
    if actual.selected_bands != expected.selected_bands or actual.rank != expected.rank:
        result.append("WRONG_BAND_OR_RANK")
    return result
