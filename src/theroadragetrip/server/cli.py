import argparse
from datetime import datetime

from ..config import load_config, cities_from_config, load_city_catalog
from ..localization import SUPPORTED_LANGUAGES
from ..game_args import parse_args

DEFAULT_PORT = 8765


def parse_server_args():
    """Reuses game_args.parse_args for every world-selection flag (bbox,
    preset, use-sample, no-cache, ...), adding the
    server-only --host/--port/--tick-rate onto the same parser."""
    config = load_config()
    city_centers, _bbox_presets = cities_from_config(config)

    parser = argparse.ArgumentParser(description="The Road Rage Trip simulation server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Address to listen on")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--tick-rate", type=float, default=30.0, help="Simulation ticks per second")
    parser.add_argument("--startup-progress", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--log-file", default=None, help="Write server logs to this UTF-8 file")
    parser.add_argument("--game-mode", choices=["career", "gig_driver", "simulation"], default="gig_driver")
    parser.add_argument("--language", choices=SUPPORTED_LANGUAGES, default=None)
    parser.add_argument("--list-cities", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--list-city-locations", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--list-saves", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--save-slot", default=None,
                        help="Gig save slot name: continue it if it exists, else start it (saves/NAME.json)")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Delete all cached map data (OSM downloads and built worlds) and exit")
    parser.add_argument("--parent-pid", type=int, default=None, help="Exit when this process (the client) exits")
    parser.add_argument("--reset-home", action="store_true", help="Forget the driver's home in every city and exit")
    parser.add_argument("--start-time", type=datetime.fromisoformat, default=None,
                        help="Gig game start, local YYYY-MM-DDTHH:MM, up to a year back (default: today 18:00)")
    parser.add_argument("--historical-weather", action=argparse.BooleanOptionalAction, default=None,
                        help="FMI observed/forecast weather for the city and game time (default: config game.historical_weather)")

    # Any municipality: a map-picker start takes its nearest one's settings.
    args = parse_args(config, city_names=list(city_centers) + [n for n in load_city_catalog() if n not in city_centers], parser=parser)
    args.no_menu = True  # a server can never show an interactive menu
    return args, config
