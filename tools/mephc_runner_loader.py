"""Test-only loader for modules in the hyphenated mephc-runner directory."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

def load_runner_module(name: str):
    path = Path(__file__).with_name("mephc-runner") / f"{name}.py"
    spec = spec_from_file_location(f"mephc_runner_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
