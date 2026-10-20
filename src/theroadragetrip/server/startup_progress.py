"""Best-effort startup status before the simulation socket is available."""
import json
import logging
import threading
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
        self.pending = None

    def __call__(self, stage, detail=""):
        now = time.monotonic()
        changed = stage != self.stage
        if changed:
            self.stage = stage
            self.history = (self.history + [stage])[-6:]
            logger.info("Startup: %s %s", stage, detail)
        if self.path is None:
            return
        if not changed and now - self.last_write < 0.2:
            # Flush the throttled detail later: the next call may be minutes away.
            if self.pending is None:
                self.pending = threading.Timer(0.25, self._flush)
                self.pending.daemon = True
                self.pending.start()
            self.detail = detail
            return
        self.detail = detail
        self.last_write = now
        self._write(now)

    def _flush(self):
        self.pending = None
        if time.monotonic() - self.last_write >= 0.2:
            self.last_write = time.monotonic()
            self._write(self.last_write)

    def _write(self, now):
        payload = {"stage": self.stage, "detail": self.detail, "elapsed_s": round(now - self.started, 1),
                   "history": self.history}
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            # A status display must never prevent the game from starting.
            logger.warning("Could not write startup status to %s", self.path, exc_info=True)
