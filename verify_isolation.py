"""Startup gate: fail closed if the runner's tool catalogue is not what we declared.

The bridge's whole safety claim is that the answering agent can reach only a
small, named allowlist of tools. A Hermes upgrade, a plugin change, or a toolset
edit can silently widen that set, so this runs before the service starts and
refuses to boot on any surprise.

Expectations are keyed by the toolset string in BRIDGE_TOOLSETS. An unknown
toolset string is a hard failure on purpose: adding a toolset means deciding what
it may expose and writing that expectation down here.

Run with the interpreter of the environment that has Hermes installed, not the
bridge's own venv:

    /path/to/hermes-env/bin/python verify_isolation.py

Note: widening toolsets has a non-obvious effect. Enabling session_search adds
tool_search/tool_describe/tool_call to the model-facing catalogue and removes
session_search from it, so the model must discover it through tool_search. The
raw catalogue keeps session_search. That is why there are two expectations.
"""

import os
import sys

HERMES_LIB = os.environ.get("BRIDGE_HERMES_LIB", "/usr/local/lib/hermes-agent")
DEFAULT_TOOLSETS = "search,session_search"

# toolset string -> (exact raw catalogue, exact model-facing catalogue)
EXPECTED = {
    "search": (
        {"web_search"},
        {"web_search"},
    ),
    "search,session_search": (
        {"session_search", "web_search"},
        {"tool_call", "tool_describe", "tool_search", "web_search"},
    ),
}


def main():
    sys.path.insert(0, HERMES_LIB)

    from hermes_cli.plugins import discover_plugins
    from model_tools import get_tool_definitions

    toolsets = os.environ.get("BRIDGE_TOOLSETS") or DEFAULT_TOOLSETS
    if toolsets not in EXPECTED:
        raise SystemExit(
            f"BLOCKED: BRIDGE_TOOLSETS={toolsets!r} has no declared expectation. "
            f"Add it to EXPECTED in {os.path.basename(__file__)} after deciding what "
            f"it may expose, then re-run."
        )
    expected_raw, expected_effective = EXPECTED[toolsets]
    enabled = toolsets.split(",")

    discover_plugins()
    raw = {entry["function"]["name"] for entry in get_tool_definitions(
        enabled_toolsets=enabled, quiet_mode=True, skip_tool_search_assembly=True)}
    effective = {entry["function"]["name"] for entry in get_tool_definitions(
        enabled_toolsets=enabled, quiet_mode=True)}

    if raw != expected_raw or effective != expected_effective:
        raise SystemExit(
            f"BLOCKED: Hermes tool isolation changed for toolsets={toolsets!r}. "
            f"raw={sorted(raw)} (expected {sorted(expected_raw)}) "
            f"effective={sorted(effective)} (expected {sorted(expected_effective)})")

    print(f"PASS: toolsets={toolsets!r} raw={sorted(raw)} effective={sorted(effective)}")


if __name__ == "__main__":
    main()
