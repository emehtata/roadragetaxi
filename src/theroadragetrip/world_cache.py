"""Versioned binary cache for normalized local game-world data."""

from __future__ import annotations

import binascii
import logging
import os
import struct
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

MAGIC = b"RWC\0"
FORMAT_VERSION = 1
COORDINATE_SYSTEM = "EPSG:3067"
_HEADER = struct.Struct("<4sHHQQ32s12s")
_DIRECTORY = struct.Struct("<8sQQI")
_VALUE = struct.Struct("<BI")
_TYPES = {"none": 0, "bool": 1, "int": 2, "float": 3, "str": 4, "list": 5, "tuple": 6, "dict": 7}
_TYPE_NAMES = {value: key for key, value in _TYPES.items()}
_SECTIONS = ("ways", "waters", "buildings", "sceneries", "places", "traffic_lights",
             "crossings", "taxi_stops", "bus_stops", "parking_spaces", "logical_intersections",
             "stop_signs", "yield_signs", "metadata")
_SECTION_CODES = {
    "buildings": "bldgs", "sceneries": "scenery",
    "traffic_lights": "signals", "crossings": "crossing",
    "logical_intersections": "intersct",
    "parking_spaces": "parking", "taxi_stops": "taxistop", "bus_stops": "busstop",
    "stop_signs": "stops", "yield_signs": "yields",
}
_SECTION_NAMES = {code: name for name, code in _SECTION_CODES.items()}


def _normalize(value: Any, way_indexes: dict[int, int] | None = None) -> Any:
    if is_dataclass(value):
        return _object_values(value, way_indexes)
    if isinstance(value, frozenset):
        return tuple(_normalize(item, way_indexes) for item in value)
    if isinstance(value, (list, tuple)):
        return type(value)(_normalize(item, way_indexes) for item in value)
    if isinstance(value, Mapping):
        return {key: _normalize(item, way_indexes) for key, item in value.items()}
    return value


class InvalidWorldCache(ValueError):
    """Raised when an RWC file fails structural validation."""


def _encode(value: Any) -> bytes:
    if value is None:
        return _VALUE.pack(_TYPES["none"], 0)
    if isinstance(value, bool):
        return _VALUE.pack(_TYPES["bool"], 1 if value else 0)
    if isinstance(value, int):
        return _VALUE.pack(_TYPES["int"], 8) + struct.pack("<q", value)
    if isinstance(value, float):
        return _VALUE.pack(_TYPES["float"], 8) + struct.pack("<d", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _VALUE.pack(_TYPES["str"], len(raw)) + raw
    if isinstance(value, (list, tuple)):
        payload = struct.pack("<I", len(value)) + b"".join(_encode(item) for item in value)
        return _VALUE.pack(_TYPES["list" if isinstance(value, list) else "tuple"], len(payload)) + payload
    if isinstance(value, Mapping):
        payload = struct.pack("<I", len(value))
        for key, item in value.items():
            payload += _encode(str(key)) + _encode(item)
        return _VALUE.pack(_TYPES["dict"], len(payload)) + payload
    raise TypeError(f"unsupported cache value: {type(value).__name__}")


def _decode(data: memoryview, offset: int = 0) -> tuple[Any, int]:
    if offset + _VALUE.size > len(data):
        raise InvalidWorldCache("truncated value header")
    type_id, size = _VALUE.unpack_from(data, offset)
    offset += _VALUE.size
    if type_id == _TYPES["none"]:
        return None, offset
    if type_id == _TYPES["bool"]:
        return bool(size), offset
    if type_id == _TYPES["int"]:
        if size != 8 or offset + 8 > len(data):
            raise InvalidWorldCache("invalid integer")
        return struct.unpack_from("<q", data, offset)[0], offset + 8
    if type_id == _TYPES["float"]:
        if size != 8 or offset + 8 > len(data):
            raise InvalidWorldCache("invalid float")
        return struct.unpack_from("<d", data, offset)[0], offset + 8
    if type_id == _TYPES["str"]:
        end = offset + size
        if end > len(data):
            raise InvalidWorldCache("truncated string")
        return bytes(data[offset:end]).decode("utf-8"), end
    end = offset + size
    if end > len(data):
        raise InvalidWorldCache("truncated container")
    if type_id in (_TYPES["list"], _TYPES["tuple"]):
        if size < 4:
            raise InvalidWorldCache("invalid sequence")
        count = struct.unpack_from("<I", data, offset)[0]
        cursor, items = offset + 4, []
        for _ in range(count):
            item, cursor = _decode(data, cursor)
            items.append(item)
        if cursor != end:
            raise InvalidWorldCache("sequence size mismatch")
        return (items if type_id == _TYPES["list"] else tuple(items)), end
    if type_id == _TYPES["dict"]:
        if size < 4:
            raise InvalidWorldCache("invalid mapping")
        count = struct.unpack_from("<I", data, offset)[0]
        cursor, result = offset + 4, {}
        for _ in range(count):
            key, cursor = _decode(data, cursor)
            item, cursor = _decode(data, cursor)
            result[key] = item
        if cursor != end:
            raise InvalidWorldCache("mapping size mismatch")
        return result, end
    raise InvalidWorldCache(f"unsupported value type {type_id}")


def _object_values(obj: Any, way_indexes: dict[int, int] | None = None) -> dict[str, Any]:
    if not is_dataclass(obj):
        return dict(obj) if isinstance(obj, Mapping) else obj
    result = {}
    for item in fields(obj):
        if not item.init:
            continue
        value = getattr(obj, item.name)
        if item.name == "road_segments" and way_indexes is not None:
            value = [way_indexes.get(id(way), -1) for way in value]
        elif item.name == "traffic_lights" and way_indexes is not None:
            value = [getattr(light, "id", None) for light in value]
        else:
            value = _normalize(value, way_indexes)
        result[item.name] = value
    return result


class BinaryWorldCacheWriter:
    """Serialize normalized MapData into an RWC file without OSM fields."""

    def write(self, path: str | os.PathLike[str], world: Any, area_id: str = "",
              osm_timestamp: int = 0) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        way_indexes = {id(way): index for index, way in enumerate(world.ways)}
        collections = {name: getattr(world, name, []) for name in _SECTIONS[:-1]}
        sections: dict[str, bytes] = {}
        for name, values in collections.items():
            records = [_object_values(value, way_indexes) for value in values]
            sections[name] = _encode(records)
        sections["metadata"] = _encode({"bounds": tuple(world.bounds), "area_id": area_id})
        area_raw = area_id.encode("utf-8")[:32].ljust(32, b"\0")
        header_size = _HEADER.size + _DIRECTORY.size * len(sections)
        offset = header_size
        directory = []
        for name in _SECTIONS:
            payload = sections[name]
            code = _SECTION_CODES.get(name, name)
            directory.append((code.encode("ascii").ljust(8, b"\0"), offset, len(payload),
                              binascii.crc32(payload) & 0xffffffff))
            offset += len(payload)
        header = _HEADER.pack(MAGIC, FORMAT_VERSION, len(sections), int(time.time()),
                              int(osm_timestamp), area_raw, COORDINATE_SYSTEM.encode())
        temporary = target.with_name(target.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(header)
            for entry in directory:
                stream.write(_DIRECTORY.pack(*entry))
            for name in _SECTIONS:
                stream.write(sections[name])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target


class BinaryWorldCacheLoader:
    """Validate and restore an RWC file into the game's dataclasses."""

    def load(self, path: str | os.PathLike[str]) -> Any:
        from .osm import MapData
        started = time.perf_counter()
        target = Path(path)
        raw = target.read_bytes()
        if len(raw) < _HEADER.size:
            raise InvalidWorldCache("file is too small")
        magic, version, section_count, _created, _osm, area_raw, coordinate = _HEADER.unpack_from(raw)
        if magic != MAGIC:
            raise InvalidWorldCache("bad magic")
        if version != FORMAT_VERSION:
            raise InvalidWorldCache(f"unsupported version {version}")
        if section_count != len(_SECTIONS):
            raise InvalidWorldCache("unsupported section count")
        if coordinate.rstrip(b"\0").decode("ascii") != COORDINATE_SYSTEM:
            raise InvalidWorldCache("unsupported coordinate system")
        directory_end = _HEADER.size + section_count * _DIRECTORY.size
        if len(raw) < directory_end:
            raise InvalidWorldCache("truncated directory")
        payloads = {}
        ranges = []
        for index in range(section_count):
            name_raw, offset, size, checksum = _DIRECTORY.unpack_from(raw, _HEADER.size + index * _DIRECTORY.size)
            code = name_raw.rstrip(b"\0").decode("ascii")
            name = _SECTION_NAMES.get(code, code)
            if name not in _SECTIONS or offset < directory_end or offset + size > len(raw):
                raise InvalidWorldCache("invalid section bounds")
            if any(offset < end and start < offset + size for start, end in ranges):
                raise InvalidWorldCache("overlapping sections")
            ranges.append((offset, offset + size))
            payload = raw[offset:offset + size]
            if binascii.crc32(payload) & 0xffffffff != checksum:
                raise InvalidWorldCache(f"checksum mismatch in {name}")
            payloads[name] = payload
        decoded = {}
        for name in _SECTIONS:
            decoded[name], end = _decode(memoryview(payloads[name]))
            if end != len(payloads[name]):
                raise InvalidWorldCache(f"trailing data in {name}")
        classes = {
            "ways": "Way", "waters": "Water", "buildings": "Building", "sceneries": "Scenery",
            "places": "Place", "traffic_lights": "TrafficLight", "crossings": "Crossing",
            "taxi_stops": "TaxiStop", "bus_stops": "BusStop", "parking_spaces": "ParkingSpace",
            "stop_signs": "StopSign", "yield_signs": "YieldSign",
        }
        import theroadragetrip.osm as osm
        restored = {}
        for name, class_name in classes.items():
            restored[name] = []
            for record in decoded[name]:
                record = dict(record)
                if class_name == "TrafficLight":
                    if isinstance(record.get("signal_group"), dict):
                        record["signal_group"] = osm.SignalGroup(**record["signal_group"])
                    record["allowed_movements"] = frozenset(record.get("allowed_movements", ()))
                restored[name].append(getattr(osm, class_name)(**record))
        restored["bounds"] = tuple(decoded["metadata"]["bounds"])
        ways = restored["ways"]
        restored["logical_intersections"] = []
        for record in decoded["logical_intersections"]:
            record = dict(record)
            approaches = []
            for approach in record.get("approaches", []):
                approach = dict(approach)
                approach["road_segments"] = [ways[i] for i in approach["road_segments"] if 0 <= i < len(ways)]
                signal_group = approach.get("signal_group")
                if isinstance(signal_group, dict):
                    approach["signal_group"] = osm.SignalGroup(**signal_group)
                approach["allowed_movements"] = frozenset(approach.get("allowed_movements", ()))
                approaches.append(osm.IntersectionApproach(**approach))
            record["approaches"] = approaches
            light_ids = set(record.get("traffic_lights", ()))
            record["traffic_lights"] = [
                light for light in restored["traffic_lights"] if light.id in light_ids
            ]
            restored["logical_intersections"].append(osm.LogicalIntersection(**record))
        world = MapData(**restored)
        logger.info(
            "[WorldCache] Loaded %s in %.1f ms: nodes=%d roads=%d buildings=%d parking spaces=%d",
            target.name, (time.perf_counter() - started) * 1000.0,
            sum(len(way.points_m) for way in world.ways), len(world.ways),
            len(world.buildings), len(world.parking_spaces),
        )
        return world


class WorldCacheManager:
    """Central cache hit/miss manager, including safe background preloading."""

    def __init__(self, cache_dir: str | os.PathLike[str] | None = None,
                 fetch_func: Callable | None = None, build_func: Callable | None = None,
                 cache_ttl: float | None = None):
        self.cache_dir = Path(cache_dir or (Path.home() / ".cache" / "RoadRageTrip" / "world"))
        self.fetch_func = fetch_func
        self.build_func = build_func
        self.cache_ttl = cache_ttl
        self.writer = BinaryWorldCacheWriter()
        self.loader = BinaryWorldCacheLoader()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="world-cache")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    @staticmethod
    def area_id(bbox: tuple[float, float, float, float]) -> str:
        return "_".join(f"{value:.6f}".replace("-", "m").replace(".", "p") for value in bbox)

    def path_for(self, area_id: str) -> Path:
        return self.cache_dir / f"{area_id}.rwc"

    def load_area(self, area_id: str, bbox=None, *, force_refresh: bool = False, **kwargs) -> Any:
        started = time.perf_counter()
        path = self.path_for(area_id)
        fresh = path.exists() and (
            self.cache_ttl is None or time.time() - path.stat().st_mtime <= self.cache_ttl
        )
        if not force_refresh and fresh:
            try:
                world = self.loader.load(path)
                logger.info("[WorldCache] Cache hit %s (%d roads, %d buildings)",
                            area_id, len(world.ways), len(world.buildings))
                logger.info("[WorldCache] Area %s ready in %.1f ms", area_id, (time.perf_counter() - started) * 1000.0)
                return world
            except (OSError, InvalidWorldCache, TypeError, ValueError) as error:
                logger.warning("[WorldCache] Invalid cache %s: %s", path, error)
                try:
                    path.unlink()
                except OSError:
                    pass
        elif path.exists() and not fresh:
            logger.info("[WorldCache] Cache expired %s", path)
        if self.fetch_func is None or self.build_func is None or bbox is None:
            raise FileNotFoundError(f"no valid world cache for {area_id}")
        logger.info("[WorldCache] Cache miss %s; downloading OpenPass JSON", area_id)
        elements = self.fetch_func(bbox, **kwargs)
        world = self.build_func(elements)
        self.writer.write(path, world, area_id=area_id)
        logger.info("[WorldCache] Cache created %s in %.1f ms", path, (time.perf_counter() - started) * 1000.0)
        return world

    def preload(self, area_id: str, bbox=None, **kwargs) -> Future:
        with self._lock:
            future = self._futures.get(area_id)
            if future is None or future.done():
                future = self._executor.submit(self.load_area, area_id, bbox, **kwargs)
                self._futures[area_id] = future
            return future

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
