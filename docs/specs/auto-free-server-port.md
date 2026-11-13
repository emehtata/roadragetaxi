# Auto-select a free server port

## Goal
If 8765 is busy, the game picks the next free port in 8765–8775 and gives that port to both
the server it launches and its own SimClient. It never connects to a server it did not launch.

## Verified current state
- `godot/startup.gd:5` `const PORT := 8765`; :1263 passes `--port PORT`; :1291 `OS.create_process`.
- :1305 adds `main.tscn`. Its `SimClient` (`sim_client.gd:18` `port := 8765`, :63 `connect_to_host`)
  starts connecting right away, so it reaches whatever process holds 8765.
- :1387 already shows `start_failed` once `OS.is_process_running(_server_pid)` is false, but by then
  the client may already be connected to a different process.
- `main.gd:200` `--port` sets `sim.port` (manual override, used when the client is run without startup).
- `transport.Listener` binds without a fallback (raises OSError). `Simulation.start`
  (`server/__init__.py:735`) already logs "listening on host:port".

## Design
- Probe method: `TCPServer.new().listen(p, "127.0.0.1") == OK`, then `stop()`, for p in 8765..8775.
  The probe does not use port 0. In Godot 4, `listen(0)` behaviour and `get_local_port()` are not
  documented for that case, and a fixed range keeps ports predictable for firewall rules and the
  Makefile. If no port in the range is free, show `start_failed` with the detail "ports 8765–8775 busy".
- Race: the probe releases the port before the server binds. If another process takes the port in
  that gap, the server's bind fails and the server exits. That case is handled by the next rule.
- Never use another process's server. Any time `_server_pid` is no longer running during loading,
  disconnect SimClient (`sim.disconnect_from_server()` or the existing close), free `_game` and show
  `start_failed`, even if the client is connected. Startup also sets `SimClient.port` before
  `add_child(_game)` so that the client connects only to the chosen port.
- Manual override: when the user passes `--port N` on the command line, startup.gd uses N and runs no probe.
  If N is busy, the server fails and the user sees `start_failed`.

## Files to change
- `godot/startup.gd`: remove `const PORT`. Add `static func find_free_port(first := 8765, last := 8775) -> int`
  (returns -1 if none is free). Add `var _port`, filled from the manual `--port` argument or the probe.
  Pass `_port` to the server args and set `_game.get_node("SimClient").port`. Extend the exit check at :1387.
- `src/theroadragetrip/server/__init__.py` `start()` / `server/cli.py`: catch `OSError` with
  `errno.EADDRINUSE`, then print `port N is in use; pass --port <free port>` to stderr, write the
  stage `error` to the startup-progress file, and exit with a non-zero code. Also print the bound
  `listening on host:port` to stdout. Python has no fallback port.

## Acceptance criteria
1. While 8765 is held by a Python socket, `find_free_port()` returns 8766, and the server launch args contain `--port 8766`.
2. When 8765–8775 are all held, the result is -1 and startup shows `start_failed`.
3. With a manual `--port 9001`, the server args and SimClient use 9001 even when 9001 is busy (no probe runs).
4. A server whose bind fails exits non-zero and writes the stage `error`. Startup shows `start_failed`, and SimClient
   is not left connected to the process that holds the port.
5. The server prints `listening on 127.0.0.1:<port>` on stdout. On EADDRINUSE it prints the `--port` hint and has no traceback.
6. `make check` and `XDG_DATA_HOME=$(mktemp -d) make godot-test` pass.
7. Manual: `python -c "import socket,time;s=socket.socket();s.bind(('127.0.0.1',8765));s.listen();time.sleep(600)" &`,
   then `make run`. The game loads, and the server log shows port 8766.

## Tests to add
- `tests/test_server_cli.py::test_busy_port_exits_with_hint`: holds a socket on a port, runs the server on that port,
  and asserts a non-zero exit, "--port" in stderr and the `error` stage. It fails today because of the bare traceback.
- `godot/tests/server_port.gd` (registered with `make godot-test`):
  `test_busy_default_picks_next` (criterion 1), `test_all_busy_returns_minus_one` (criterion 2),
  `test_manual_port_not_probed` (criterion 3). Each holds ports with `TCPServer`. They fail today because no probe exists.
- `godot/tests/server_port.gd::test_exited_server_shows_start_failed`: uses a fake `_server_pid` for a process that has
  already exited (for example, a launched `true`) while SimClient is connected to a stub TCPServer. It asserts that the
  start_failed text is shown and that SimClient is disconnected. It fails today because the connection stays open.
  Run it with `XDG_DATA_HOME=$(mktemp -d)`.

## Commands
- `make check`
- `XDG_DATA_HOME=$(mktemp -d) make godot-test`
- the manual demo in criterion 7

## Out of scope
- Port 0 / OS-assigned ports, a fallback port on the Python side, changes to the Makefile `PORT`, and remote (non-localhost) servers.

## Status
- Tester verdict: PASS.
- The new Godot tests fail without the change because `find_free_port` and the related port functions do not exist yet.
- Busy-port case: the server exits non-zero with the `--port` hint and the `error` stage, with no traceback.
- Open gap: the full-game manual demo (criterion 7, 8765 held, game loads on 8766) was NOT run end to end. Covered by unit and headless tests only.
- Note: a busy-port server does the full world build before bind, so the `--port` hint arrives late. Bind earlier as a follow-up.
