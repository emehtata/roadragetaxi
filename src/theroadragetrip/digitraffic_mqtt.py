"""Live push data from Digitraffic Road over MQTT (docs/digitraffic-mqtt.md).

Only with the live clock and realtime road data both on: MQTT is "now"
data, wrong at any other game time. paho's own thread owns the socket,
reconnects with backoff and decodes JSON; the simulation only drains a
bounded number of messages per tick. Nothing is cached or saved: live data
cannot be replayed (the REST data in digitraffic_road.py can).

Source: Fintraffic / digitraffic.fi, license CC 4.0 BY.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Callable, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

HOST = "tie.digitraffic.fi"
PORT = 443
PATH = "/mqtt"
USER = "RoadRageTrip/live-feed"
QUEUE_MAX = 2000  # oldest dropped beyond this: a stalled tick never grows memory
RECONNECT_S = (1, 300)


def _paho_client():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path=PATH, headers={"Digitraffic-User": USER})
    client.tls_set()
    client.reconnect_delay_set(*RECONNECT_S)
    return client


class LiveFeed:
    """Subscribed topics in, (topic, message, received unix s) out. Each
    root's `<root>/status` gives `updated` (unix s) and is kept apart."""

    def __init__(self, topics: Iterable[str], client_factory: Callable = _paho_client,
                 clock: Callable[[], float] = time.time) -> None:
        self.topics = list(topics)
        self.clock = clock
        self.queue: deque = deque(maxlen=QUEUE_MAX)
        self.connected = False
        self.received = 0
        self.dropped = 0
        self.last_message_at: Optional[float] = None
        self.updated: dict = {}  # root -> the feed's own last update, unix s
        self.client = client_factory()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect_async(HOST, PORT, keepalive=60)  # offline: retried, never blocks startup
        self.client.loop_start()

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            logger.warning("Digitraffic MQTT refused: %s", reason_code)
            return
        self.connected = True
        logger.info("Digitraffic MQTT connected, %d topics", len(self.topics))
        if self.topics:  # again after every reconnect: the session is clean
            client.subscribe([(topic, 0) for topic in self.topics])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if self.connected:
            logger.info("Digitraffic MQTT disconnected: %s", reason_code)
        self.connected = False

    def _on_message(self, client, userdata, message) -> None:
        try:
            body = json.loads(message.payload)
        except ValueError:
            return
        now = self.clock()
        self.received += 1
        self.last_message_at = now
        root, _, rest = message.topic.partition("/")
        if rest == "status":
            if isinstance(body, dict) and isinstance(body.get("updated"), (int, float)):
                self.updated[root] = body["updated"]
            return
        if len(self.queue) == self.queue.maxlen:
            self.dropped += 1
        self.queue.append((message.topic, body, now))

    def drain(self, limit: int) -> List[Tuple[str, object, float]]:
        """At most `limit` queued messages, oldest first (the tick's budget)."""
        out = []
        while self.queue and len(out) < limit:
            out.append(self.queue.popleft())
        return out

    def diagnostics(self) -> dict:
        now = self.clock()
        return {"connected": self.connected, "topics": self.topics, "received": self.received,
                "queued": len(self.queue), "dropped": self.dropped,
                "last_message_age_s": None if self.last_message_at is None else round(now - self.last_message_at, 1),
                "feed_age_s": {root: round(now - updated, 1) for root, updated in self.updated.items()}}
