import logging
import json

from ..config import cities_from_config
from ..main.cli import configure_logging
from .cli import parse_server_args
from . import run_server

logger = logging.getLogger(__name__)


def main() -> None:
    args, config = parse_server_args()
    if args.list_cities:
        print(json.dumps(list(cities_from_config(config)[0]), ensure_ascii=False))
        return
    if args.clear_cache:  # main()'s "Clear all map cache": [OSM files, world caches] removed
        from ..osm.cache import clear_osm_cache
        from ..world_cache import clear_world_cache

        print(json.dumps([clear_osm_cache(), clear_world_cache()]))
        return
    configure_logging(args.log_level, file_logging=config.getboolean("game", "file_logging", fallback=False))
    server = run_server(args, config)
    logger.info(
        "Headless simulation server ready: city=%s tick_rate=%.1f",
        server.chosen_city, server.tick_rate,
    )
    server.run_forever()


if __name__ == "__main__":
    main()
