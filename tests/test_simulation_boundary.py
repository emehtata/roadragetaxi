"""The simulation's player command (client-server-01.md)."""

import theroadragetrip.simulation as simulation


def test_player_command_defaults_are_inert():
    command = simulation.PlayerCommand()
    assert (command.throttle, command.brake, command.steer_left, command.steer_right) == (0.0, 0.0, 0.0, 0.0)
    assert (command.forward, command.turn, command.sprint) == (0.0, 0.0, False)
    assert command.refuel is False
