import argparse

from ..config import load_config, cities_from_config
from ..main.cli import parse_args

DEFAULT_PORT = 8765


def parse_server_args():
    """Reuses main.cli.parse_args for every world-selection flag (bbox,
    preset, use-sample, no-cache, ...) so the server and the Pygame client
    accept identical world arguments from one definition, adding the
    server-only --host/--port/--tick-rate onto the same parser."""
    config = load_config()
    city_centers, _bbox_presets = cities_from_config(config)

    parser = argparse.ArgumentParser(description="The Road Rage Trip simulation server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Address to listen on")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--tick-rate", type=float, default=30.0, help="Simulation ticks per second")
    parser.add_argument("--game-mode", choices=["career", "gig_driver"], default="gig_driver")
    parser.add_argument("--language", choices=["en", "fi"], default=None)
    parser.add_argument("--list-cities", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--historical-weather", action=argparse.BooleanOptionalAction, default=None,
                        help="FMI observed/forecast weather for the city and game time (default: config game.historical_weather)")

    args = parse_args(config, city_names=list(city_centers), parser=parser)
    args.no_menu = True  # a server can never show an interactive menu
    return args, config
