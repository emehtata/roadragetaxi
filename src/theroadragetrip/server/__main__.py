import logging

from ..main.cli import configure_logging
from .cli import parse_server_args
from . import run_server

logger = logging.getLogger(__name__)


def main() -> None:
    args, config = parse_server_args()
    configure_logging(args.log_level, file_logging=config.getboolean("game", "file_logging", fallback=False))
    server = run_server(args, config)
    logger.info(
        "Headless simulation server ready: city=%s tick_rate=%.1f",
        server.chosen_city, server.tick_rate,
    )
    server.run_forever()


if __name__ == "__main__":
    main()
