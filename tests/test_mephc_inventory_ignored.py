from tools.mephc_runner_loader import load_runner_module

inventory = load_runner_module("inventory")


def test_ignored_runtime_and_legacy_classification():
    assert inventory.classify(
        ".relayctl/runner/heartbeat.json", tracked=False, project_id="MEPHC"
    ) == "INSTALLED_REBUILDABLE_RUNTIME"
    assert inventory.classify(
        ".relayctl/runner/heartbeat.json", tracked=False, project_id="TRILATT"
    ) == "AMBIGUOUS_FAIL_CLOSED"


def test_inventory_enumerates_git_ignored_files():
    text = open(inventory.__file__, encoding="utf-8").read()
    assert '"ls-files", "-z", "--others", "-i", "--exclude-standard"' in text
