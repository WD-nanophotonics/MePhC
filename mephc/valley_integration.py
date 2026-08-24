"""Solver-neutral retained-domain plans and fail-closed Berry reduction."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

SOURCE_GRID_MIDPOINT_V1 = "SOURCE_GRID_MIDPOINT_V1"
MEPHC_CLIPPED_RETAINED_DOMAIN_V1 = "MEPHC_CLIPPED_RETAINED_DOMAIN_V1"
SOURCE_H = 1.0 / 36.0
EPS = 1e-12
_ESTIMATORS = (SOURCE_GRID_MIDPOINT_V1, MEPHC_CLIPPED_RETAINED_DOMAIN_V1)


class IntegrationPlanError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _area(poly):
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[i][1] * poly[(i + 1) % len(poly)][0]
        for i in range(len(poly))
    )


def _ccw(poly):
    return list(poly) if _area(poly) > 0 else list(reversed(poly))


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in(poly, point):
    ordered = _ccw(poly)
    return all(
        _cross(a, b, point) >= -EPS
        for a, b in zip(ordered, ordered[1:] + ordered[:1])
    )


def _clip(poly, a, b, inside=True):
    if not poly:
        return []
    out = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        vp, vq = _cross(a, b, p), _cross(a, b, q)
        pin = vp >= -EPS if inside else vp <= EPS
        qin = vq >= -EPS if inside else vq <= EPS
        if pin:
            out.append(p)
        if pin != qin and abs(vp - vq) > EPS:
            t = vp / (vp - vq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def _intersection(*polys):
    out = list(polys[0])
    for poly in polys[1:]:
        for a, b in zip(_ccw(poly), _ccw(poly)[1:] + _ccw(poly)[:1]):
            out = _clip(out, a, b, True)
            if len(out) < 3:
                return []
    return out


def _intersection_area(*polys):
    polygon = _intersection(*polys)
    return abs(_area(polygon)) if len(polygon) >= 3 else 0.0


def _square(q, side):
    half = side / 2
    return [
        (q[0] - half, q[1] - half),
        (q[0] + half, q[1] - half),
        (q[0] + half, q[1] + half),
        (q[0] - half, q[1] + half),
    ]


def _regular(center, radius, sides, rotation=0.0):
    return [
        (
            center[0] + radius * math.cos(rotation + 2 * math.pi * i / sides),
            center[1] + radius * math.sin(rotation + 2 * math.pi * i / sides),
        )
        for i in range(sides)
    ]


def _neg(poly):
    return [(-x, -y) for x, y in poly]


def _scale(poly, center, factor):
    return [
        (center[0] + factor * (x - center[0]), center[1] + factor * (y - center[1]))
        for x, y in poly
    ]


def _subtract(poly, hole):
    active = [list(poly)]
    result = []
    for a, b in zip(_ccw(hole), _ccw(hole)[1:] + _ccw(hole)[:1]):
        next_active = []
        for piece in active:
            inside = _clip(piece, a, b, True)
            outside = _clip(piece, a, b, False)
            if len(outside) >= 3 and abs(_area(outside)) > EPS:
                result.append(outside)
            if len(inside) >= 3 and abs(_area(inside)) > EPS:
                next_active.append(inside)
        active = next_active
    return result


def _triangles(poly):
    polygon = _ccw(poly)
    result = []
    for i in range(1, len(polygon) - 1):
        triangle = [polygon[0], polygon[i], polygon[i + 1]]
        weight = abs(_area(triangle))
        if weight > EPS:
            result.append((triangle, weight))
    return result


@dataclass(frozen=True)
class RetainedDomain:
    case: str
    outer: tuple[tuple[float, float], ...]
    exclusions: tuple[tuple[tuple[float, float], ...], ...]
    delta_k: float
    delta_gamma: float

    @property
    def digest(self):
        return _digest(self.to_dict())

    @property
    def area_q2(self):
        return abs(_area(self.outer)) - sum(
            _intersection_area(self.outer, hole) for hole in self.exclusions
        )

    def to_dict(self):
        return {
            "case": self.case,
            "outer": [list(x) for x in self.outer],
            "exclusions": [[list(x) for x in hole] for hole in self.exclusions],
            "delta_K": self.delta_k,
            "delta_Gamma": self.delta_gamma,
        }


def build_source_bound_domain(fr):
    if float(fr) not in (0.0, 0.4):
        raise ValueError("supported cases are fr=0 and fr=0.4")
    delta_k, delta_gamma = (0.10, 0.10) if float(fr) == 0.0 else (0.05, 0.13)
    k = (2.0 / 3.0, 0.0)
    k_prime = (-2.0 / 3.0, 0.0)
    radius = 2.0 / 3.0
    k_triangle = _regular(k, radius, 3, math.pi / 3.0)
    k_prime_triangle = _neg(k_triangle)
    outer = _scale(k_prime_triangle, k_prime, (radius - delta_k) / radius)
    holes = tuple(
        tuple(tuple(x) for x in _regular(vertex, delta_gamma, 6, 0.0))
        for vertex in k_prime_triangle
    )
    return RetainedDomain(
        f"fr={float(fr):g}",
        tuple(tuple(x) for x in outer),
        holes,
        delta_k,
        delta_gamma,
    )


def _grid_nodes(domain):
    min_x = min(x for x, _ in domain.outer) - SOURCE_H
    max_x = max(x for x, _ in domain.outer) + SOURCE_H
    min_y = min(y for _, y in domain.outer) - SOURCE_H
    max_y = max(y for _, y in domain.outer) + SOURCE_H
    for i in range(math.floor(min_x * 36) - 1, math.ceil(max_x * 36) + 2):
        for j in range(math.floor(min_y * 36) - 1, math.ceil(max_y * 36) + 2):
            yield i, j, (i / 36, j / 36)


def _retained(domain, q):
    return _point_in(domain.outer, q) and not any(
        _point_in(hole, q) for hole in domain.exclusions
    )


def _cell_fragments(domain, q):
    pieces = [_intersection(domain.outer, _square(q, SOURCE_H))]
    if not pieces[0] or len(pieces[0]) < 3:
        return []
    for hole in domain.exclusions:
        next_pieces = []
        for piece in pieces:
            next_pieces.extend(_subtract(piece, hole))
        pieces = next_pieces
    return pieces


def _sample_id(domain, estimator_id, i, j, fragment=0, triangle=0):
    if estimator_id == SOURCE_GRID_MIDPOINT_V1:
        return f"{domain.case};grid_i={i};grid_j={j};estimator=SOURCE_GRID"
    return (
        f"{domain.case};grid_i={i};grid_j={j};fragment_index={fragment};"
        f"triangle_index={triangle};estimator=MEPHC_CLIPPED"
    )


def _row(domain, estimator_id, sample_id, q, weight, i, j, fragment=None, triangle=None):
    point = tuple(float(x) for x in q)
    return {
        "ESTIMATOR_ID": estimator_id,
        "SAMPLE_ID": sample_id,
        "PUBLIC_Q": point,
        "PUBLIC_Q_HEX_FLOATS": tuple(value.hex() for value in point),
        "WEIGHT_Q2": float(weight),
        "DOMAIN_ID_OR_DIGEST": domain.digest,
        "GRID_INDEX": (i, j),
        "FRAGMENT_INDEX": fragment,
        "TRIANGLE_INDEX": triangle,
    }


def _canonical_plan(plan):
    rows = []
    for row in sorted(plan["ROWS"], key=lambda item: item["SAMPLE_ID"]):
        rows.append(
            {
                key: row[key]
                for key in (
                    "ESTIMATOR_ID",
                    "SAMPLE_ID",
                    "PUBLIC_Q_HEX_FLOATS",
                    "WEIGHT_Q2",
                    "DOMAIN_ID_OR_DIGEST",
                    "GRID_INDEX",
                    "FRAGMENT_INDEX",
                    "TRIANGLE_INDEX",
                )
            }
        )
    return rows


def _expected_total_weight(rows):
    return sum(
        float(row["WEIGHT_Q2"])
        for row in sorted(rows, key=lambda item: item["SAMPLE_ID"])
    )


def build_integration_plan(domain, estimator_id):
    if estimator_id not in _ESTIMATORS:
        raise IntegrationPlanError("unknown estimator")
    rows = []
    for i, j, q in _grid_nodes(domain):
        if estimator_id == SOURCE_GRID_MIDPOINT_V1:
            if _retained(domain, q):
                rows.append(
                    _row(
                        domain,
                        estimator_id,
                        _sample_id(domain, estimator_id, i, j),
                        q,
                        SOURCE_H**2,
                        i,
                        j,
                    )
                )
            continue
        cell = _square(q, SOURCE_H)
        outer_area = _intersection_area(domain.outer, cell)
        hole_area = sum(
            _intersection_area(domain.outer, hole, cell)
            for hole in domain.exclusions
        )
        weight = max(0.0, outer_area - hole_area)
        if weight <= EPS:
            continue
        full = (
            abs(weight - SOURCE_H**2) <= 1e-12
            and _retained(domain, q)
            and all(_point_in(domain.outer, point) for point in cell)
            and not any(
                _intersection_area(domain.outer, hole, cell) > EPS
                for hole in domain.exclusions
            )
        )
        if full:
            rows.append(
                _row(
                    domain,
                    estimator_id,
                    _sample_id(domain, estimator_id, i, j),
                    q,
                    weight,
                    i,
                    j,
                    0,
                    0,
                )
            )
            continue
        index = 0
        for fragment_index, piece in enumerate(_cell_fragments(domain, q)):
            for triangle_index, (triangle, triangle_weight) in enumerate(_triangles(piece)):
                sample = tuple(
                    sum(point[d] for point in triangle) / 3.0 for d in (0, 1)
                )
                rows.append(
                    _row(
                        domain,
                        estimator_id,
                        _sample_id(
                            domain,
                            estimator_id,
                            i,
                            j,
                            index,
                            index,
                        ),
                        sample,
                        triangle_weight,
                        i,
                        j,
                        index,
                        index,
                    )
                )
                index += 1
    plan = {
        "ESTIMATOR_ID": estimator_id,
        "DOMAIN_DIGEST": domain.digest,
        "ROWS": tuple(rows),
        "SAMPLE_COUNT": len(rows),
        "TOTAL_WEIGHT_Q2": _expected_total_weight(rows),
    }
    plan["PLAN_DIGEST"] = _digest(_canonical_plan(plan))
    validate_integration_plan(plan)
    return plan


def _require_hex_binding(row):
    q = row.get("PUBLIC_Q")
    hex_values = row.get("PUBLIC_Q_HEX_FLOATS")
    if (
        not isinstance(q, (tuple, list))
        or len(q) != 2
        or not all(math.isfinite(float(value)) for value in q)
        or not isinstance(hex_values, (tuple, list))
        or len(hex_values) != 2
        or tuple(str(value) for value in hex_values)
        != tuple(float(value).hex() for value in q)
    ):
        raise IntegrationPlanError("PUBLIC_Q_HEX_FLOATS_BINDING_INVALID")


def validate_integration_plan(plan):
    if not isinstance(plan, dict):
        raise IntegrationPlanError("invalid plan")
    estimator_id = plan.get("ESTIMATOR_ID")
    rows = plan.get("ROWS")
    domain_digest = plan.get("DOMAIN_DIGEST")
    if estimator_id not in _ESTIMATORS or not isinstance(rows, (tuple, list)):
        raise IntegrationPlanError("invalid plan")
    if not isinstance(domain_digest, str) or not domain_digest:
        raise IntegrationPlanError("DOMAIN_DIGEST_REQUIRED")
    sample_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise IntegrationPlanError("invalid plan row")
        sample_id = row.get("SAMPLE_ID")
        if (
            row.get("ESTIMATOR_ID") != estimator_id
            or not isinstance(sample_id, str)
            or not sample_id
            or sample_id in sample_ids
        ):
            raise IntegrationPlanError("mixed or duplicate estimator/sample")
        sample_ids.add(sample_id)
        if row.get("DOMAIN_ID_OR_DIGEST") != domain_digest:
            raise IntegrationPlanError("DOMAIN_DIGEST_ROW_BINDING_INVALID")
        _require_hex_binding(row)
        weight = row.get("WEIGHT_Q2")
        if not math.isfinite(float(weight)) or float(weight) <= 0:
            raise IntegrationPlanError("positive weights required")
    if plan.get("SAMPLE_COUNT") != len(rows):
        raise IntegrationPlanError("SAMPLE_COUNT_TAMPERED")
    expected_total = _expected_total_weight(rows)
    if (
        not math.isfinite(float(plan.get("TOTAL_WEIGHT_Q2")))
        or float(plan["TOTAL_WEIGHT_Q2"]) != expected_total
    ):
        raise IntegrationPlanError("TOTAL_WEIGHT_Q2_TAMPERED")
    plan_digest = plan.get("PLAN_DIGEST")
    if not isinstance(plan_digest, str) or plan_digest != _digest(_canonical_plan(plan)):
        raise IntegrationPlanError("PLAN_DIGEST_TAMPERED")
    return True


def _require_exact_row_binding(plan, expected, row, band_id):
    if row.get("ESTIMATOR_ID") != plan["ESTIMATOR_ID"]:
        raise IntegrationPlanError("MIXED_ESTIMATOR_PLAN_REJECTED")
    if row.get("SAMPLE_ID") != expected["SAMPLE_ID"]:
        raise IntegrationPlanError("SAMPLE_BINDING_INVALID")
    if row.get("BAND_ID") != band_id:
        raise IntegrationPlanError("band mismatch")
    if row.get("PLAN_DIGEST") != plan["PLAN_DIGEST"]:
        raise IntegrationPlanError("PLAN_DIGEST_ROW_BINDING_INVALID")
    if row.get("DOMAIN_DIGEST") != plan["DOMAIN_DIGEST"]:
        raise IntegrationPlanError("DOMAIN_DIGEST_ROW_BINDING_INVALID")
    if tuple(row.get("PUBLIC_Q_HEX_FLOATS", ())) != tuple(
        expected["PUBLIC_Q_HEX_FLOATS"]
    ):
        raise IntegrationPlanError("PUBLIC_Q_HEX_ROW_BINDING_INVALID")
    weight = row.get("WEIGHT_Q2")
    if not math.isfinite(float(weight)) or float(weight) != float(expected["WEIGHT_Q2"]):
        raise IntegrationPlanError("FAILED_WEIGHT_REMOVAL_OR_RENORMALIZATION")


def reduce_supplied_berry_rows(plan, berry_rows, band_id):
    validate_integration_plan(plan)
    if not isinstance(berry_rows, (tuple, list)):
        raise IntegrationPlanError("berry rows collection required")
    required = {row["SAMPLE_ID"]: row for row in plan["ROWS"]}
    grouped = {}
    for row in berry_rows:
        if not isinstance(row, dict):
            raise IntegrationPlanError("invalid Berry row")
        sample_id = row.get("SAMPLE_ID")
        if sample_id not in required:
            raise IntegrationPlanError("unknown sample row")
        _require_exact_row_binding(plan, required[sample_id], row, band_id)
        grouped.setdefault(sample_id, []).append(row)
    missing = set(required) - set(grouped)
    if missing:
        raise IntegrationPlanError("MISSING_ROW")
    if any(len(values) != 1 for values in grouped.values()):
        raise IntegrationPlanError("DUPLICATE_ROW")
    statuses = [grouped[sample_id][0] for sample_id in required]
    for row in statuses:
        status = row.get("STATUS")
        if status not in ("QUALIFIED_REPORTED", "NOT_REPORTED_WITH_REASON"):
            raise IntegrationPlanError("terminal status required")
        if status == "QUALIFIED_REPORTED":
            value = row.get("OMEGA_Q")
            if value is None or not math.isfinite(float(value)):
                raise IntegrationPlanError("NAN_OR_INF_REPORTED_VALUE")
            if "REASON" in row and row.get("REASON") is not None:
                raise IntegrationPlanError("QUALIFIED_REASON_PAYLOAD_INVALID")
        else:
            reason = row.get("REASON")
            if not isinstance(reason, str) or not reason.strip():
                raise IntegrationPlanError("FAILED_ROW_REASON_REQUIRED")
            if "OMEGA_Q" in row:
                raise IntegrationPlanError("FAILED_ROW_NUMERIC_PAYLOAD_REJECTED")
    not_reported = [
        row for row in statuses if row["STATUS"] == "NOT_REPORTED_WITH_REASON"
    ]
    status_digest = _digest(
        sorted(
            [
                {
                    key: row.get(key)
                    for key in ("SAMPLE_ID", "BAND_ID", "STATUS", "REASON")
                }
                for row in statuses
            ],
            key=lambda item: item["SAMPLE_ID"],
        )
    )
    base = {
        "ESTIMATOR_ID": plan["ESTIMATOR_ID"],
        "DOMAIN_DIGEST": plan["DOMAIN_DIGEST"],
        "PLAN_DIGEST": plan["PLAN_DIGEST"],
        "STATUS_DIGEST": status_digest,
        "BAND_ID": band_id,
        "SAMPLE_COUNT": len(statuses),
        "TOTAL_WEIGHT_Q2": plan["TOTAL_WEIGHT_Q2"],
        "QUALIFIED_SAMPLE_COUNT": len(statuses) - len(not_reported),
        "NOT_REPORTED_SAMPLE_COUNT": len(not_reported),
        "NORMALIZATION_ID": "PUBLIC_Q_OMEGA_OVER_2PI",
        "COMPLETE_STATUS": "INCOMPLETE_NOT_REPORTED" if not_reported else "COMPLETE",
    }
    if not_reported:
        return {
            **base,
            "FLUX_Q": "NOT_EMITTED",
            "VALLEY_CHERN": "NOT_EMITTED",
            "FAILURE_PROVENANCE": {
                "status": "NOT_REPORTED_WITH_REASON",
                "sample_ids": [row["SAMPLE_ID"] for row in not_reported],
            },
        }
    flux = sum(float(row["OMEGA_Q"]) * float(row["WEIGHT_Q2"]) for row in statuses)
    return {**base, "FLUX_Q": flux, "VALLEY_CHERN": flux / (2 * math.pi)}


def build_berry_row(plan, plan_row, band_id, status, omega_q=None, reason=None):
    if not isinstance(plan, dict) or not isinstance(plan_row, dict):
        raise IntegrationPlanError("plan and plan row required")
    if "PLAN_DIGEST" not in plan or "DOMAIN_DIGEST" not in plan:
        raise IntegrationPlanError("plan provenance required")
    if plan_row.get("DOMAIN_ID_OR_DIGEST") != plan["DOMAIN_DIGEST"]:
        raise IntegrationPlanError("DOMAIN_DIGEST_ROW_BINDING_INVALID")
    row = {
        "ESTIMATOR_ID": plan_row["ESTIMATOR_ID"],
        "SAMPLE_ID": plan_row["SAMPLE_ID"],
        "BAND_ID": band_id,
        "PLAN_DIGEST": plan["PLAN_DIGEST"],
        "DOMAIN_DIGEST": plan["DOMAIN_DIGEST"],
        "PUBLIC_Q_HEX_FLOATS": tuple(plan_row["PUBLIC_Q_HEX_FLOATS"]),
        "STATUS": status,
        "WEIGHT_Q2": plan_row["WEIGHT_Q2"],
    }
    if status == "QUALIFIED_REPORTED":
        if reason is not None or omega_q is None or not math.isfinite(float(omega_q)):
            raise IntegrationPlanError("QUALIFIED_REPORTED_PAYLOAD_INVALID")
        row["OMEGA_Q"] = omega_q
    elif status == "NOT_REPORTED_WITH_REASON":
        if omega_q is not None or not isinstance(reason, str) or not reason.strip():
            raise IntegrationPlanError("NOT_REPORTED_WITH_REASON_PAYLOAD_INVALID")
        row["REASON"] = reason
    else:
        raise IntegrationPlanError("terminal status required")
    return row
