"""Best-effort startup status before the simulation socket is available."""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class StartupProgress:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.started = time.monotonic()
        self.last_write = float("-inf")
        self.stage = None
        self.history = []

    def __call__(self, stage, detail=""):
        now = time.monotonic()
        changed = stage != self.stage
        if changed:
            self.stage = stage
            self.history = (self.history + [stage])[-6:]
            logger.info("Startup: %s %s", stage, detail)
        if self.path is None or (not changed and now - self.last_write < 0.2):
            return
        self.last_write = now
        payload = {"stage": stage, "detail": detail, "elapsed_s": round(now - self.started, 1),
                   "history": self.history}
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            # A status display must never prevent the game from starting.
            logger.warning("Could not write startup status to %s", self.path, exc_info=True)
