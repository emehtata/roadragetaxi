"""Regression tests for client-server-015.md Phase 1.5: a normal
single-player launch must run advance_simulation() directly, in-process,
with no SimulationServer/socket/JSON/shadow-object machinery anywhere in
its hot path. --connect (an explicit opt-in to the experimental client/
server architecture) may still use all of that.

main()'s interactive per-frame loop is a large, blocking Pygame loop that
isn't practically unit-testable frame-by-frame - no existing test in this
codebase does that either (test_client_server_integration.py/
test_server_headless.py talk to SimulationServer directly, never through
main()'s own loop). These tests instead check the actual invariants the
spec cares about via static source inspection, the same shape as
test_simulation_boundary.py's no-pygame-import AST check on simulation.py.
"""
import ast
import importlib
import inspect
import os
import subprocess
import sys

# theroadragetrip/__init__.py does `from .main import main`, which rebinds
# the `main` attribute on the *package* to the function - `import
# theroadragetrip.main as x` would resolve through that same shadowed
# attribute and bind x to the function, not the submodule. Go through
# sys.modules directly to get the real submodule.
main_module = importlib.import_module("theroadragetrip.main")


def _main_source() -> str:
    return inspect.getsource(main_module.main)


def _find_if_connection_not_none(source: str) -> ast.If:
    """The per-frame `if connection is not None: <networked> else:
    <direct>` branch - the one and only place a tick actually happens.
    There's a second, unrelated `if connection is not None:
    connection.close()` (no else) earlier in main() for cleanup between
    city changes - `orelse` being non-empty is what distinguishes them."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "connection"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.IsNot)
            and node.orelse
        ):
            return node
    raise AssertionError("could not locate the per-frame `if connection is not None: ... else:` branch in main()")


def _segment(source: str, stmts) -> str:
    return "\n".join(ast.get_source_segment(source, stmt) or "" for stmt in stmts)


def test_main_module_import_does_not_load_the_server_package():
    """The SimulationServer import inside main() is deferred/local
    specifically so ordinary single-player startup never pays that cost.
    Run in a fresh subprocess: other test modules in this same suite
    import theroadragetrip.server directly, which would pollute
    sys.modules for an in-process check."""
    repo_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([repo_src, os.environ.get("PYTHONPATH", "")]))
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import theroadragetrip.main; import sys; "
            "assert 'theroadragetrip.server' not in sys.modules, "
            "sorted(m for m in sys.modules if 'theroadragetrip' in m)",
        ],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr


def test_normal_startup_never_constructs_a_simulationserver_or_listener():
    source = _main_source()
    # Substring on the *construction* pattern, not the bare class name -
    # main() legitimately still mentions "SimulationServer" in comments
    # explaining that it's no longer created here.
    assert "SimulationServer(" not in source
    assert "Listener(" not in source


def test_direct_single_player_path_calls_advance_simulation_with_no_shadow_state():
    source = _main_source()
    node = _find_if_connection_not_none(source)
    networked_branch = _segment(source, node.body)
    direct_branch = _segment(source, node.orelse)

    assert "advance_simulation(" in direct_branch
    for banned in ("apply_server_state", "interpolate_state", "ShadowVehicle", "connection.send", "connection.try_recv"):
        assert banned not in direct_branch, f"{banned!r} must not appear in the direct single-player path"

    # Sanity check the split is meaningful, not just an empty/misdetected
    # branch - the networked (--connect) branch still legitimately uses
    # all of this.
    assert "apply_server_state" in networked_branch
    assert "interpolate_state" in networked_branch
    assert "connection.send" in networked_branch


def test_connect_flag_still_gates_the_networked_path():
    source = _main_source()
    assert "args.connect" in source
    assert "transport.connect(" in source
