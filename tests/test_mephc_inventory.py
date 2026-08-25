from __future__ import annotations

import importlib.util
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "tools" / "mephc-runner"


def load_inventory():
    spec = importlib.util.spec_from_file_location("mephc_inventory", SOURCE / "inventory.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_scope_is_fixed():
    inventory = load_inventory()
    assert set(inventory.REPOSITORIES) == {"MEPHC", "TRILATT", "SQRLATT", "GMAILCOURIER"}
    assert inventory.REPOSITORIES["MEPHC"] == Path("/home/icy/MePhC")


def test_unknown_residue_fails_closed():
    inventory = load_inventory()
    assert inventory.classify("historical/result.json", tracked=False) == "AMBIGUOUS_FAIL_CLOSED"


def test_generated_and_secret_classification():
    inventory = load_inventory()
    assert inventory.classify("tests/__pycache__/x.pyc", tracked=False) == "DISPOSABLE_GENERATED"
    assert inventory.classify("runtime/oauth-token.json", tracked=False) == "SECRET_OR_CREDENTIAL"
    assert inventory.classify("mephc/source.py", tracked=True) == "CANONICAL_SOURCE"


def test_inventory_source_has_no_delete_primitive():
    text = (SOURCE / "inventory.py").read_text(encoding="utf-8")
    for token in ("unlink(", "rmtree(", "remove(", "git clean", "git reset"):
        assert token not in text
