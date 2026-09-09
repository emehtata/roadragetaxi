import logging
import os
import threading
import time
from typing import Callable, List, Optional, Tuple

import requests


logger = logging.getLogger(__name__)


_overpass_stats_lock = threading.Lock()


_overpass_stats = {
    "requests": 0,
    "responses": 0,
    "last_status": 0,
    "last_elements": 0,
    "last_endpoint": "",
}


def get_overpass_diagnostics() -> dict[str, object]:
    with _overpass_stats_lock:
        return dict(_overpass_stats)


# Public Overpass instances hand out 429s with their own, much longer
# cooldown than any one caller's retry backoff - immediately retrying the
# same endpoint on the next fetch (e.g. the next tile crossing, seconds
# later) just draws another 429 and stretches out how long that endpoint
# stays rate-limited. Remember which endpoints are cooling down across
# calls, keyed by URL (shared by every fetch_osm_ways() caller/thread), and
# skip straight to a mirror instead of re-poking a still-limited one.
_endpoint_cooldown_until: dict[str, float] = {}
_endpoint_cooldown_lock = threading.Lock()
# https://wiki.openstreetmap.org/wiki/Overpass_API : "If you receive an
# HTTP error code such as 429 or 406, pause for 30 seconds before making a
# new request." Default to double that as a margin unless the endpoint's
# own Retry-After says otherwise.
DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0


def _endpoint_on_cooldown(endpoint: str) -> bool:
    with _endpoint_cooldown_lock:
        return time.monotonic() < _endpoint_cooldown_until.get(endpoint, 0.0)


def _mark_endpoint_rate_limited(endpoint: str, retry_after_header: Optional[str]) -> None:
    cooldown_s = DEFAULT_RATE_LIMIT_COOLDOWN_S
    if retry_after_header:
        try:
            cooldown_s = max(cooldown_s, float(retry_after_header))
        except ValueError:
            pass  # Retry-After can also be an HTTP date; not worth parsing here.
    with _endpoint_cooldown_lock:
        _endpoint_cooldown_until[endpoint] = time.monotonic() + cooldown_s


DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


OVERPASS_HEADERS = {
    "User-Agent": "TheRoadRageTrip/0.0.1 (https://github.com/theroadragetrip; educational driving game poc)"
}


def configure_user_agent(user_agent_id: str) -> None:
    """Attach the persistent first-run identity to Overpass requests."""
    OVERPASS_HEADERS["User-Agent"] = (
        "TheRoadRageTrip/0.0.1 "
        f"(https://github.com/theroadragetrip; educational driving game poc; id={user_agent_id})"
    )


def fetch_osm_ways(
    bbox: Tuple[float, float, float, float],
    endpoints: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    force_refresh: bool = False,
) -> List[dict]:
    # Re-read from the package each call so tests can monkeypatch
    # theroadragetrip.osm.load_osm_cache / .save_osm_cache.
    from . import load_osm_cache, save_osm_cache

    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:25];
    (
      node["highway"="traffic_signals"]({south},{west},{north},{east});
            node["highway"="stop"]({south},{west},{north},{east});
      node["highway"="crossing"]({south},{west},{north},{east});
      node["highway"="taxi_stop"]({south},{west},{north},{east});
    node["highway"="bus_stop"]({south},{west},{north},{east});
    node["public_transport"~"platform|stop_position"]({south},{west},{north},{east});
      node["amenity"="taxi"]({south},{west},{north},{east});
      node["crossing"]({south},{west},{north},{east});
    node["entrance"]({south},{west},{north},{east});
    node["amenity"="parking_space"]({south},{west},{north},{east});
      node["place"~"suburb|neighbourhood|quarter|village|town|city|hamlet"]({south},{west},{north},{east});
    node["name"]({south},{west},{north},{east});
      way["highway"]({south},{west},{north},{east});
    way["name"]({south},{west},{north},{east});
      way["barrier"="kerb"]({south},{west},{north},{east});
      way["natural"="water"]({south},{west},{north},{east});
    way["natural"="bay"]({south},{west},{north},{east});
    way["natural"="strait"]({south},{west},{north},{east});
      way["waterway"]({south},{west},{north},{east});
      way["landuse"="reservoir"]({south},{west},{north},{east});
      way["building"]({south},{west},{north},{east});
    way["amenity"="parking"]({south},{west},{north},{east});
    way["landuse"="parking"]({south},{west},{north},{east});
    way["amenity"="parking_space"]({south},{west},{north},{east});
      way["landuse"~"forest|grass|park|meadow|residential|commercial|industrial|recreation_ground"]({south},{west},{north},{east});
      way["leisure"~"park|garden|pitch|playground"]({south},{west},{north},{east});
      way["natural"~"wood|scrub|grass|sand|heath"]({south},{west},{north},{east});
      way["place"~"suburb|neighbourhood|quarter|village"]({south},{west},{north},{east});
      relation["natural"="water"]({south},{west},{north},{east});
    relation["natural"="bay"]({south},{west},{north},{east});
    relation["natural"="strait"]({south},{west},{north},{east});
      relation["landuse"="reservoir"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    relation["amenity"="parking"]({south},{west},{north},{east});
    relation["landuse"="parking"]({south},{west},{north},{east});
      relation["leisure"="park"]({south},{west},{north},{east});
      relation["landuse"~"forest|grass|park|meadow"]({south},{west},{north},{east});
      relation["place"~"suburb|neighbourhood|quarter"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """

    if progress_callback:
        progress_callback(0.1, "Checking cache...")

    force_refresh = force_refresh or os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")
    if not force_refresh:
        cached = load_osm_cache(bbox)
        if cached is not None:
            logger.info("Loaded OSM data from local cache")
            if progress_callback:
                progress_callback(0.5, f"Loaded {len(cached)} cached elements")
            return cached

    endpoints = endpoints or DEFAULT_OVERPASS_ENDPOINTS
    env_eps = os.getenv("OVERPASS_ENDPOINTS")
    if env_eps:
        endpoints = [e.strip() for e in env_eps.split(",") if e.strip()]
    last_err = None

    for ep in endpoints:
        # Skip an endpoint still cooling down from an earlier 429, as long
        # as some other endpoint might actually be available right now; if
        # every endpoint is cooling down, there's no better option, so try
        # anyway rather than failing the fetch outright.
        if _endpoint_on_cooldown(ep) and any(not _endpoint_on_cooldown(other) for other in endpoints):
            logger.info("Skipping rate-limited endpoint %s (cooldown active)", ep)
            continue
        for attempt in range(1, 4):
            try:
                if progress_callback:
                    progress_callback(0.25, f"Fetching scenery from {ep[:35]}...")
                with _overpass_stats_lock:
                    _overpass_stats["requests"] += 1
                logger.info("Overpass request: endpoint=%s attempt=%d", ep, attempt)
                r = requests.post(ep, data={"data": query}, headers=OVERPASS_HEADERS, timeout=60)
                with _overpass_stats_lock:
                    _overpass_stats["responses"] += 1
                    _overpass_stats["last_status"] = r.status_code
                    _overpass_stats["last_endpoint"] = ep
                logger.info(
                    "Overpass response: endpoint=%s status=%d bytes=%d",
                    ep,
                    r.status_code,
                    len(getattr(r, "content", b"")),
                )
                if r.status_code in (429, 406):
                    # Per https://wiki.openstreetmap.org/wiki/Overpass_API :
                    # a 429 or 406 means back off this endpoint for at least
                    # 30s before trying it again.
                    _mark_endpoint_rate_limited(ep, r.headers.get("Retry-After"))
                    last_err = Exception(f"{r.status_code} rate limited by {ep}")
                    logger.warning(
                        "Overpass rate limited (%d) %s; switching endpoint (attempt %d)",
                        r.status_code,
                        ep,
                        attempt,
                    )
                    break
                if r.status_code >= 500:
                    last_err = Exception(f"{r.status_code} Server Error from {ep}")
                    time.sleep(2 ** (attempt - 1))
                    continue
                r.raise_for_status()
                if progress_callback:
                    progress_callback(0.5, "Parsing OSM payload...")
                data = r.json()
                els = data.get("elements", [])
                with _overpass_stats_lock:
                    _overpass_stats["last_elements"] = len(els)
                logger.info("Overpass response data: endpoint=%s elements=%d", ep, len(els))
                logger.info("Loaded OSM data from %s (%d elements)", ep, len(els))
                try:
                    save_osm_cache(bbox, els)
                except Exception:
                    pass
                if progress_callback:
                    progress_callback(0.6, f"Downloaded {len(els)} elements")
                return els
            except requests.exceptions.Timeout as e:
                last_err = e
                logger.warning("Timeout from %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.ConnectionError as e:
                last_err = e
                logger.warning("Connection error to %s (attempt %d)", ep, attempt)
                time.sleep(2 ** (attempt - 1))
                continue
            except requests.exceptions.HTTPError as e:
                last_err = e
                status = getattr(e.response, "status_code", None)
                if status and 400 <= status < 500:
                    logger.warning("HTTP %s from %s; moving to next endpoint", status, ep)
                    break
                logger.warning("HTTP error from %s (attempt %d): %s", ep, attempt, e)
                time.sleep(2 ** (attempt - 1))
                continue
            except Exception as e:
                last_err = e
                logger.warning("Error when contacting %s: %s", ep, e)
                time.sleep(2 ** (attempt - 1))
                continue

    raise last_err or Exception("Failed to fetch OSM data from any Overpass endpoint.")
