import logging
import json
import multiprocessing

from ..config import cities_from_config, load_city_catalog
from ..game_args import configure_logging
from ..performance import tune_interpreter
from ..parent_watch import exit_with_parent
from .cli import parse_server_args
from . import run_server

logger = logging.getLogger(__name__)


def main() -> None:
    multiprocessing.freeze_support()
    tune_interpreter()
    args, config = parse_server_args()
    if args.list_cities:
        print(json.dumps(list(cities_from_config(config)[0]), ensure_ascii=False))
        return
    if args.list_city_locations:
        # The menu's cities, then every other municipality (menu: false)
        # for the map picker's nearest-municipality settings.
        centers = cities_from_config(config)[0]
        others = {name: c for name, c in load_city_catalog().items() if name not in centers}
        print(json.dumps([
            {"name": name, "latitude": latitude, "longitude": longitude, "menu": name in centers}
            for name, (latitude, longitude) in {**centers, **others}.items()
        ], ensure_ascii=False))
        return
    if args.clear_cache:  # [OSM files, world caches] removed
        from ..osm.cache import clear_osm_cache
        from ..world_cache import clear_world_cache

        print(json.dumps([clear_osm_cache(), clear_world_cache()]))
        return
    if args.reset_home:
        from ..config import CONFIG_PATH
        from ..home import homes_path

        homes_path(CONFIG_PATH).unlink(missing_ok=True)
        print("[]")
        return
    if args.parent_pid:
        exit_with_parent(args.parent_pid)
    configure_logging(args.log_level, file_logging=config.getboolean("game", "file_logging", fallback=False))
    server = run_server(args, config)
    logger.info(
        "Headless simulation server ready: city=%s tick_rate=%.1f",
        server.chosen_city, server.tick_rate,
    )
    server.run_forever()


if __name__ == "__main__":
    main()
