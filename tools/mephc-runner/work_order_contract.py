#!/home/icy/miniconda3/envs/mp/bin/python
"""Canonical machine contract and legacy adapter for MePhC work orders."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "mephc-work-order-contract-v1"
SHA64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{2,127}$")
CAPABILITY = re.compile(r"^[a-z][a-z0-9_.-]{2,95}$")
WORK_ORDER = re.compile(r"^[A-Z][A-Z0-9._-]{2,127}$")
MACHINE_PREFIX = "WORK_ORDER_CONTRACT_JSON="
POLICY_FORBIDDEN = {
    "shell", "arbitrary_shell", "wsl", "arbitrary_wsl", "browser",
    "arbitrary_path_read", "arbitrary_process_control", "main_promotion",
}


class ContractError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}:{detail}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and CAPABILITY.fullmatch(item) for item in value):
        raise ContractError("WORK_ORDER_CONTRACT_SCHEMA_INVALID", field)
    return sorted(set(value))


def _bindings(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 32:
        raise ContractError("WORK_ORDER_CONTRACT_SCHEMA_INVALID", "retention_bindings")
    result, seen = [], set()
    for item in value:
        if (not isinstance(item, dict) or set(item) != {"retention_id", "expected_sha256"}
                or not isinstance(item.get("retention_id"), str)
                or not IDENTIFIER.fullmatch(item["retention_id"])
                or not isinstance(item.get("expected_sha256"), str)
                or not SHA64.fullmatch(item["expected_sha256"])
                or item["retention_id"] in seen):
            raise ContractError("WORK_ORDER_CONTRACT_SCHEMA_INVALID", "retention_bindings")
        seen.add(item["retention_id"])
        result.append({"retention_id": item["retention_id"], "expected_sha256": item["expected_sha256"]})
    return sorted(result, key=lambda item: item["retention_id"])


def validate(value: Any, expected_work_order_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema", "work_order_id", "required_capabilities", "authorized_actions", "retention_bindings"
    }:
        raise ContractError("WORK_ORDER_CONTRACT_SCHEMA_INVALID", "keys")
    work_order_id = value.get("work_order_id")
    if (not isinstance(work_order_id, str) or not WORK_ORDER.fullmatch(work_order_id)
            or expected_work_order_id is not None and work_order_id != expected_work_order_id
            or value.get("schema") != SCHEMA):
        raise ContractError("WORK_ORDER_CONTRACT_SCHEMA_INVALID", "identity")
    result = {
        "schema": SCHEMA,
        "work_order_id": work_order_id,
        "required_capabilities": _strings(value["required_capabilities"], "required_capabilities"),
        "authorized_actions": _strings(value["authorized_actions"], "authorized_actions"),
        "retention_bindings": _bindings(value["retention_bindings"]),
        "contract_mode": "machine",
    }
    result["contract_sha256"] = hashlib.sha256(_canonical({key: result[key] for key in (
        "schema", "work_order_id", "required_capabilities", "authorized_actions", "retention_bindings"
    )})).hexdigest()
    return result


def _legacy_lines(text: str) -> list[str]:
    normalized = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normalized.split("\n")]


def _legacy_contract(text: str, work_order_id: str) -> dict[str, Any]:
    lines = _legacy_lines(text)
    pairs: dict[str, str] = {}
    for index, line in enumerate(lines[:-1]):
        if line.startswith("RETENTION_ID=") and lines[index + 1].startswith("EXPECTED_SHA256="):
            pairs[line.split("=", 1)[1]] = lines[index + 1].split("=", 1)[1]
    prefixed: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for line in lines:
        if "_RETENTION_ID=" in line:
            prefix, value = line.split("_RETENTION_ID=", 1)
            if re.fullmatch(r"[A-Z0-9_]+", prefix):
                prefixed[prefix] = value
        elif "_SHA256=" in line:
            prefix, value = line.split("_SHA256=", 1)
            if re.fullmatch(r"[A-Z0-9_]+", prefix):
                hashes[prefix] = value
    for prefix, retention_id in prefixed.items():
        if prefix in hashes:
            pairs[retention_id] = hashes[prefix]
    bindings = [{"retention_id": key, "expected_sha256": value} for key, value in pairs.items()
                if IDENTIFIER.fullmatch(key) and SHA64.fullmatch(value)]
    required: list[str] = []
    authorized: list[str] = []
    for line in lines:
        if line.startswith("REQUIRED_TYPED_CAPABILITY="):
            required.append(line.split("=", 1)[1])
        elif line.startswith("AUTHORIZED_TYPED_ACTION="):
            authorized.append(line.split("=", 1)[1])
    if bindings:
        required.extend(("retention.search", "retention.inspect"))
    raw = {"schema": SCHEMA, "work_order_id": work_order_id,
           "required_capabilities": sorted(set(item for item in required if CAPABILITY.fullmatch(item))),
           "authorized_actions": sorted(set(item for item in authorized if CAPABILITY.fullmatch(item))),
           "retention_bindings": bindings}
    result = validate(raw, work_order_id)
    result["contract_mode"] = "legacy_adapter"
    return result


def parse(text: str, work_order_id: str) -> dict[str, Any]:
    if not isinstance(text, str) or not isinstance(work_order_id, str):
        raise ContractError("WORK_ORDER_CONTRACT_INVALID")
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith(MACHINE_PREFIX):
            try:
                return validate(json.loads(line[len(MACHINE_PREFIX):]), work_order_id)
            except json.JSONDecodeError as exc:
                raise ContractError("WORK_ORDER_CONTRACT_JSON_INVALID") from exc
    return _legacy_contract(text, work_order_id)


def binding_map(contract: dict[str, Any]) -> dict[str, str]:
    return {item["retention_id"]: item["expected_sha256"] for item in contract["retention_bindings"]}


def authority_conflicts(contract: dict[str, Any]) -> list[str]:
    requested = set(contract["required_capabilities"]) | set(contract["authorized_actions"])
    return sorted(requested & POLICY_FORBIDDEN)
