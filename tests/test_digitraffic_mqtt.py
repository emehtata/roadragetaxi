"""Digitraffic MQTT live feed (digitraffic_mqtt.py) against a fake paho client."""
from types import SimpleNamespace

from theroadragetrip import digitraffic_mqtt as dm


class FakeClient:
    def __init__(self):
        self.subscribed, self.calls = [], []

    def subscribe(self, topics):
        self.subscribed.append(topics)

    def connect_async(self, *args, **kwargs):
        self.calls.append("connect_async")

    def loop_start(self):
        self.calls.append("loop_start")


def _feed(topics=("weather-v2/status", "maintenance-v2/routes/state-roads")):
    now = [1000.0]
    client = FakeClient()
    feed = dm.LiveFeed(topics, client_factory=lambda: client, clock=lambda: now[0])
    return feed, client, now


def _message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload)


def test_subscribes_on_every_connect_and_tracks_the_connection():
    feed, client, _ = _feed()
    feed.start()
    assert client.calls == ["connect_async", "loop_start"]  # never a blocking connect
    ok = SimpleNamespace(is_failure=False)
    feed._on_connect(client, None, None, ok)
    feed._on_disconnect(client, None, None, ok)
    feed._on_connect(client, None, None, ok)
    assert feed.connected and len(client.subscribed) == 2
    feed._on_connect(client, None, None, SimpleNamespace(is_failure=True))
    assert len(client.subscribed) == 2


def test_status_is_kept_apart_data_is_queued_and_junk_ignored():
    feed, client, now = _feed()
    feed._on_message(client, None, _message("weather-v2/status", b'{"updated": 990}'))
    feed._on_message(client, None, _message("maintenance-v2/routes/state-roads", b'{"x": 25.4, "y": 65.0}'))
    feed._on_message(client, None, _message("maintenance-v2/routes/state-roads", b"not json"))
    now[0] = 1003.0
    assert feed.drain(10) == [("maintenance-v2/routes/state-roads", {"x": 25.4, "y": 65.0}, 1000.0)]
    diagnostics = feed.diagnostics()
    assert diagnostics["feed_age_s"] == {"weather-v2": 13.0} and diagnostics["received"] == 2
    assert diagnostics["last_message_age_s"] == 3.0


def test_the_queue_is_bounded_and_drained_in_budgets(monkeypatch):
    monkeypatch.setattr(dm, "QUEUE_MAX", 3)
    feed, client, _ = _feed()
    for i in range(5):
        feed._on_message(client, None, _message("weather-v2/1/1", b'{"value": %d}' % i))
    assert feed.dropped == 2
    assert [body["value"] for _, body, _ in feed.drain(2)] == [2, 3]  # oldest first, within the budget
    assert [body["value"] for _, body, _ in feed.drain(2)] == [4]
