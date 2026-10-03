#!/usr/bin/env python3
"""Build and validate a compact Finland drivable-road dataset from OSM PBF."""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator, Mapping
from urllib.parse import unquote


MAGIC = b"RRTROAD"
FORMAT_VERSION = 1
V2_FORMAT_VERSION = 2
COORDINATE_SCALE = 10_000_000
HEADER = struct.Struct("<7sBBIQQ")  # magic, version, coordinate exponent, flags, counts
NODE = struct.Struct("<qii")
WAY = struct.Struct("<qBbbHHBI")
UINT16 = struct.Struct("<H")
NODE_ID = struct.Struct("<q")
V2_HEADER = struct.Struct("<7sBBI" + "Q" * 11)
V2_NODE = struct.Struct("<ii")
V2_WAY_PREFIX = struct.Struct("<qIBBb")
UINT32 = struct.Struct("<I")

DRIVABLE_HIGHWAY_TYPES = frozenset({
    "motorway", "motorway_link", "trunk", "trunk_link", "primary",
    "primary_link", "secondary", "secondary_link", "tertiary",
    "tertiary_link", "unclassified", "residential", "living_street",
    "service", "road",
})
HIGHWAY_TYPES = tuple(sorted(DRIVABLE_HIGHWAY_TYPES))
HIGHWAY_TO_CODE = {name: index for index, name in enumerate(HIGHWAY_TYPES)}

FLAG_BRIDGE = 1
FLAG_TUNNEL = 2
FLAG_ROUNDABOUT = 4


class RoadDatasetError(ValueError):
    pass


def _write_uvarint(stream: BinaryIO, value: int) -> None:
    if value < 0:
        raise RoadDatasetError(f"negative unsigned varint: {value}")
    while value >= 0x80:
        stream.write(bytes(((value & 0x7F) | 0x80,)))
        value >>= 7
    stream.write(bytes((value,)))


def _read_uvarint(stream: BinaryIO) -> int:
    value = 0
    for shift in range(0, 70, 7):
        byte = _read_exact(stream, 1)[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
    raise RoadDatasetError("oversized variable-length integer")


def _write_svarint(stream: BinaryIO, value: int) -> None:
    _write_uvarint(stream, (value << 1) ^ (value >> 63))


def _read_svarint(stream: BinaryIO) -> int:
    value = _read_uvarint(stream)
    return (value >> 1) ^ -(value & 1)


@dataclass(frozen=True)
class RoadWay:
    osm_id: int
    highway: str
    node_ids: tuple[int, ...]
    oneway: int = 0
    layer: int = 0
    lanes: int = 1
    maxspeed_kmh: int = 50
    name: str = ""
    ref: str = ""
    junction: str = ""
    surface: str = ""
    bridge: bool = False
    tunnel: bool = False


@dataclass(frozen=True)
class RoadDataset:
    nodes: dict[int, tuple[int, int]]
    ways: tuple[RoadWay, ...]


def encode_coordinate(value: float) -> int:
    encoded = round(value * COORDINATE_SCALE)
    if not -(2**31) <= encoded < 2**31:
        raise RoadDatasetError(f"coordinate outside int32 range: {value}")
    return encoded


def decode_coordinate(value: int) -> float:
    return value / COORDINATE_SCALE


def _write_string(stream: BinaryIO, value: str) -> None:
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise RoadDatasetError("road metadata string exceeds 65535 UTF-8 bytes")
    stream.write(UINT16.pack(len(encoded)))
    stream.write(encoded)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise RoadDatasetError("truncated road dataset")
    return data


def _read_string(stream: BinaryIO) -> str:
    size, = UINT16.unpack(_read_exact(stream, UINT16.size))
    try:
        return _read_exact(stream, size).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RoadDatasetError("invalid UTF-8 road metadata") from exc


class RoadDatasetWriter:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.node_count = 0
        self.way_count = 0
        stream.write(HEADER.pack(MAGIC, FORMAT_VERSION, 7, 0, 0, 0))

    def write_node(self, osm_id: int, latitude: int, longitude: int) -> None:
        self.stream.write(NODE.pack(osm_id, latitude, longitude))
        self.node_count += 1

    def write_way(self, way: RoadWay) -> None:
        try:
            highway_code = HIGHWAY_TO_CODE[way.highway]
        except KeyError as exc:
            raise RoadDatasetError(f"unsupported highway type: {way.highway}") from exc
        if len(way.node_ids) < 2:
            raise RoadDatasetError(f"way {way.osm_id} has fewer than two nodes")
        if way.oneway not in (-1, 0, 1):
            raise RoadDatasetError(f"invalid oneway value for way {way.osm_id}: {way.oneway}")
        flags = (
            (FLAG_BRIDGE if way.bridge else 0)
            | (FLAG_TUNNEL if way.tunnel else 0)
            | (FLAG_ROUNDABOUT if way.junction == "roundabout" else 0)
        )
        if not -128 <= way.layer <= 127:
            raise RoadDatasetError(f"layer outside int8 range for way {way.osm_id}: {way.layer}")
        self.stream.write(WAY.pack(
            way.osm_id, highway_code, way.oneway, way.layer,
            min(65535, max(1, way.lanes)),
            min(65535, max(1, way.maxspeed_kmh)),
            flags, len(way.node_ids),
        ))
        for node_id in way.node_ids:
            self.stream.write(NODE_ID.pack(node_id))
        for value in (way.name, way.ref, way.junction, way.surface):
            _write_string(self.stream, value)
        self.way_count += 1

    def finish(self) -> None:
        end = self.stream.tell()
        self.stream.seek(0)
        self.stream.write(HEADER.pack(
            MAGIC, FORMAT_VERSION, 7, 0, self.node_count, self.way_count,
        ))
        self.stream.seek(end)


class V2DatasetWriter:
    """Streaming v2 writer backed by temporary section files."""

    def __init__(self, directory: Path):
        self.nodes_path = directory / "nodes.bin"
        self.way_offsets_path = directory / "way_offsets.bin"
        self.ways_path = directory / "ways.bin"
        self.geometry_path = directory / "geometry.bin"
        self.nodes_stream = self.nodes_path.open("wb")
        self.way_offsets_stream = self.way_offsets_path.open("wb")
        self.ways_stream = self.ways_path.open("wb")
        self.geometry_stream = self.geometry_path.open("wb")
        self.node_indices: dict[int, int] = {}
        self.latitudes = array.array("i")
        self.longitudes = array.array("i")
        self.strings = [""]
        self.string_ids = {"": 0}
        self.node_count = 0
        self.way_count = 0
        self.geometry_count = 0
        self.road_length_m = 0.0

    def write_node(self, osm_id: int, latitude: int, longitude: int) -> None:
        if osm_id in self.node_indices:
            raise RoadDatasetError(f"duplicate node ID: {osm_id}")
        self.node_indices[osm_id] = self.node_count
        self.latitudes.append(latitude)
        self.longitudes.append(longitude)
        self.nodes_stream.write(V2_NODE.pack(latitude, longitude))
        self.node_count += 1

    def _string_id(self, value: str) -> int:
        existing = self.string_ids.get(value)
        if existing is not None:
            return existing
        index = len(self.strings)
        self.string_ids[value] = index
        self.strings.append(value)
        return index

    def write_way(self, way: RoadWay) -> None:
        try:
            highway_code = HIGHWAY_TO_CODE[way.highway]
            local_indices = tuple(self.node_indices[node_id] for node_id in way.node_ids)
        except KeyError as exc:
            raise RoadDatasetError(f"way {way.osm_id} has unsupported highway or missing node {exc.args[0]}") from exc
        if len(local_indices) < 2:
            raise RoadDatasetError(f"way {way.osm_id} has fewer than two nodes")
        if way.oneway not in (-1, 0, 1):
            raise RoadDatasetError(f"invalid oneway value for way {way.osm_id}: {way.oneway}")
        if not -128 <= way.layer <= 127:
            raise RoadDatasetError(f"layer outside int8 range for way {way.osm_id}: {way.layer}")

        geometry_offset = self.geometry_stream.tell()
        if geometry_offset > 0xFFFFFFFF:
            raise RoadDatasetError("v2 geometry section exceeds 4 GiB")
        _write_uvarint(self.geometry_stream, local_indices[0])
        previous = local_indices[0]
        for local_index in local_indices[1:]:
            _write_svarint(self.geometry_stream, local_index - previous)
            previous = local_index

        oneway_bits = {0: 0, 1: 1, -1: 2}[way.oneway]
        flags = (
            oneway_bits
            | (FLAG_BRIDGE << 2 if way.bridge else 0)
            | (FLAG_TUNNEL << 2 if way.tunnel else 0)
            | (FLAG_ROUNDABOUT << 2 if way.junction == "roundabout" else 0)
        )
        way_offset = self.ways_stream.tell()
        if way_offset > 0xFFFFFFFF:
            raise RoadDatasetError("v2 way-record section exceeds 4 GiB")
        self.way_offsets_stream.write(UINT32.pack(way_offset))
        self.ways_stream.write(V2_WAY_PREFIX.pack(
            way.osm_id, geometry_offset, highway_code, flags, way.layer,
        ))
        for value in (
            len(local_indices), way.lanes, way.maxspeed_kmh,
            self._string_id(way.name), self._string_id(way.ref),
            self._string_id(way.junction), self._string_id(way.surface),
        ):
            _write_uvarint(self.ways_stream, value)

        for first, second in zip(local_indices, local_indices[1:]):
            first_coord = (self.latitudes[first], self.longitudes[first])
            second_coord = (self.latitudes[second], self.longitudes[second])
            self.road_length_m += _haversine_m(first_coord, second_coord)
        self.geometry_count += len(local_indices)
        self.way_count += 1

    def finish(self, output_path: Path) -> dict[str, int]:
        final_way_offset = self.ways_stream.tell()
        if final_way_offset > 0xFFFFFFFF:
            raise RoadDatasetError("v2 way-record section exceeds 4 GiB")
        self.way_offsets_stream.write(UINT32.pack(final_way_offset))
        self.close()

        string_offsets_path = self.nodes_path.parent / "string_offsets.bin"
        string_data_path = self.nodes_path.parent / "string_data.bin"
        with string_offsets_path.open("wb") as offsets, string_data_path.open("wb") as data:
            for value in self.strings:
                if data.tell() > 0xFFFFFFFF:
                    raise RoadDatasetError("v2 string section exceeds 4 GiB")
                offsets.write(UINT32.pack(data.tell()))
                data.write(value.encode("utf-8"))
            offsets.write(UINT32.pack(data.tell()))

        section_paths = (
            self.nodes_path, self.way_offsets_path, self.ways_path,
            self.geometry_path, string_offsets_path, string_data_path,
        )
        offsets = []
        position = V2_HEADER.size
        for path in section_paths:
            offsets.append(position)
            position += path.stat().st_size
        file_size = position
        with output_path.open("wb") as output:
            output.write(V2_HEADER.pack(
                MAGIC, V2_FORMAT_VERSION, 7, 0,
                self.node_count, self.way_count, self.geometry_count, len(self.strings),
                *offsets, file_size,
            ))
            for path in section_paths:
                with path.open("rb") as section:
                    shutil.copyfileobj(section, output, length=1024 * 1024)
        return {
            "nodes": self.node_count,
            "ways": self.way_count,
            "geometry_points": self.geometry_count,
            "strings": len(self.strings),
        }

    def close(self) -> None:
        for stream in (
            self.nodes_stream, self.way_offsets_stream, self.ways_stream,
            self.geometry_stream,
        ):
            if not stream.closed:
                stream.close()


def write_road_dataset(
    path: Path,
    nodes: Mapping[int, tuple[int, int]],
    ways: Iterable[RoadWay],
) -> None:
    """Write a small/in-memory dataset. The full-PBF builder streams instead."""
    path = Path(path)
    temp_path = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("w+b") as stream:
            writer = RoadDatasetWriter(stream)
            for osm_id, (latitude, longitude) in sorted(nodes.items()):
                writer.write_node(osm_id, latitude, longitude)
            for way in ways:
                writer.write_way(way)
            writer.finish()
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_header(stream: BinaryIO) -> tuple[int, int]:
    magic, version, coordinate_exponent, flags, node_count, way_count = HEADER.unpack(
        _read_exact(stream, HEADER.size)
    )
    if magic != MAGIC:
        raise RoadDatasetError("invalid road dataset magic")
    if version != FORMAT_VERSION:
        raise RoadDatasetError(f"unsupported road dataset version: {version}")
    if coordinate_exponent != 7 or flags != 0:
        raise RoadDatasetError("unsupported road dataset encoding")
    return node_count, way_count


def _read_way(stream: BinaryIO, node_ids_present: set[int]) -> RoadWay:
    osm_id, code, oneway, layer, lanes, maxspeed, flags, ref_count = WAY.unpack(
        _read_exact(stream, WAY.size)
    )
    if code >= len(HIGHWAY_TYPES):
        raise RoadDatasetError(f"invalid highway code for way {osm_id}: {code}")
    if flags & ~(FLAG_BRIDGE | FLAG_TUNNEL | FLAG_ROUNDABOUT):
        raise RoadDatasetError(f"unknown flags for way {osm_id}: {flags}")
    if oneway not in (-1, 0, 1) or not lanes or not maxspeed or ref_count < 2:
        raise RoadDatasetError(f"malformed way record: {osm_id}")
    node_ids = tuple(NODE_ID.unpack(_read_exact(stream, NODE_ID.size))[0] for _ in range(ref_count))
    missing = next((node_id for node_id in node_ids if node_id not in node_ids_present), None)
    if missing is not None:
        raise RoadDatasetError(f"way {osm_id} references missing node {missing}")
    name, ref, junction, surface = (_read_string(stream) for _ in range(4))
    return RoadWay(
        osm_id=osm_id,
        highway=HIGHWAY_TYPES[code],
        node_ids=node_ids,
        oneway=oneway,
        layer=layer,
        lanes=lanes,
        maxspeed_kmh=maxspeed,
        name=name,
        ref=ref,
        junction=junction,
        surface=surface,
        bridge=bool(flags & FLAG_BRIDGE),
        tunnel=bool(flags & FLAG_TUNNEL),
    )


def _read_nodes(stream: BinaryIO, node_count: int) -> dict[int, tuple[int, int]]:
    nodes = {}
    for _ in range(node_count):
        osm_id, latitude, longitude = NODE.unpack(_read_exact(stream, NODE.size))
        if osm_id in nodes:
            raise RoadDatasetError(f"duplicate node ID: {osm_id}")
        if not -900_000_000 <= latitude <= 900_000_000:
            raise RoadDatasetError(f"invalid latitude for node {osm_id}")
        if not -1_800_000_000 <= longitude <= 1_800_000_000:
            raise RoadDatasetError(f"invalid longitude for node {osm_id}")
        nodes[osm_id] = (latitude, longitude)
    return nodes


def _load_v1_dataset(path: Path) -> RoadDataset:
    with Path(path).open("rb") as stream:
        node_count, way_count = _read_header(stream)
        nodes = _read_nodes(stream, node_count)
        node_ids_present = set(nodes)
        ways = tuple(_read_way(stream, node_ids_present) for _ in range(way_count))
        if stream.read(1):
            raise RoadDatasetError("trailing data after final way record")
    return RoadDataset(nodes, ways)


def _validate_v1_dataset(path: Path) -> dict[str, int]:
    with Path(path).open("rb") as stream:
        node_count, way_count = _read_header(stream)
        nodes = _read_nodes(stream, node_count)
        node_ids_present = set(nodes)
        del nodes
        for _ in range(way_count):
            _read_way(stream, node_ids_present)
        if stream.read(1):
            raise RoadDatasetError("trailing data after final way record")
    return {"nodes": node_count, "ways": way_count}


def _file_version(path: Path) -> int:
    with Path(path).open("rb") as stream:
        prefix = _read_exact(stream, 8)
    if prefix[:7] != MAGIC:
        raise RoadDatasetError("invalid road dataset magic")
    return prefix[7]


def _read_v2_header(stream: BinaryIO) -> dict[str, int]:
    values = V2_HEADER.unpack(_read_exact(stream, V2_HEADER.size))
    magic, version, coordinate_exponent, flags = values[:4]
    if magic != MAGIC or version != V2_FORMAT_VERSION:
        raise RoadDatasetError("invalid v2 road dataset header")
    if coordinate_exponent != 7 or flags != 0:
        raise RoadDatasetError("unsupported v2 road dataset encoding")
    names = (
        "node_count", "way_count", "geometry_count", "string_count",
        "node_offset", "way_offsets_offset", "way_records_offset",
        "geometry_offset", "string_offsets_offset", "string_data_offset",
        "file_size",
    )
    header = dict(zip(names, values[4:]))
    offsets = [header[name] for name in names[4:10]] + [header["file_size"]]
    if offsets[0] != V2_HEADER.size or offsets != sorted(offsets):
        raise RoadDatasetError("invalid v2 section offsets")
    if header["way_offsets_offset"] - header["node_offset"] != header["node_count"] * V2_NODE.size:
        raise RoadDatasetError("v2 node section size does not match node count")
    if header["way_records_offset"] - header["way_offsets_offset"] != (header["way_count"] + 1) * UINT32.size:
        raise RoadDatasetError("v2 way-offset section size does not match way count")
    if header["string_data_offset"] - header["string_offsets_offset"] != (header["string_count"] + 1) * UINT32.size:
        raise RoadDatasetError("v2 string-offset section size does not match string count")
    return header


def _read_v2_strings(stream: BinaryIO, header: Mapping[str, int]) -> list[str]:
    stream.seek(header["string_offsets_offset"])
    offsets = [UINT32.unpack(_read_exact(stream, UINT32.size))[0] for _ in range(header["string_count"] + 1)]
    data_size = header["file_size"] - header["string_data_offset"]
    if offsets != sorted(offsets) or offsets[-1] != data_size:
        raise RoadDatasetError("invalid v2 string offsets")
    stream.seek(header["string_data_offset"])
    data = _read_exact(stream, data_size)
    try:
        return [data[offsets[i]:offsets[i + 1]].decode("utf-8") for i in range(header["string_count"])]
    except UnicodeDecodeError as exc:
        raise RoadDatasetError("invalid UTF-8 in v2 string table") from exc


def _read_v2_way(
    record_stream: BinaryIO,
    geometry_stream: BinaryIO,
    strings: list[str],
    node_count: int,
    geometry_section_offset: int,
    geometry_section_end: int,
    record_end: int,
) -> RoadWay:
    osm_id, geometry_offset, highway_code, flags, layer = V2_WAY_PREFIX.unpack(
        _read_exact(record_stream, V2_WAY_PREFIX.size)
    )
    values = [_read_uvarint(record_stream) for _ in range(7)]
    geometry_count, lanes, maxspeed, name_id, ref_id, junction_id, surface_id = values
    if record_stream.tell() != record_end:
        raise RoadDatasetError(f"v2 way record boundary mismatch for way {osm_id}")
    if highway_code >= len(HIGHWAY_TYPES) or geometry_count < 2 or not lanes or not maxspeed:
        raise RoadDatasetError(f"malformed v2 way record: {osm_id}")
    if flags & ~0x1F or flags & 0x03 == 0x03:
        raise RoadDatasetError(f"invalid v2 flags for way {osm_id}: {flags}")
    string_ids = (name_id, ref_id, junction_id, surface_id)
    if any(index >= len(strings) for index in string_ids):
        raise RoadDatasetError(f"invalid v2 string reference for way {osm_id}")

    geometry_start = geometry_section_offset + geometry_offset
    if not geometry_section_offset <= geometry_start < geometry_section_end:
        raise RoadDatasetError(f"invalid v2 geometry offset for way {osm_id}")
    geometry_stream.seek(geometry_start)
    local_index = _read_uvarint(geometry_stream)
    node_ids = [local_index]
    for _ in range(geometry_count - 1):
        local_index += _read_svarint(geometry_stream)
        node_ids.append(local_index)
    if geometry_stream.tell() > geometry_section_end:
        raise RoadDatasetError(f"v2 geometry crosses its section boundary for way {osm_id}")
    if any(not 0 <= index < node_count for index in node_ids):
        raise RoadDatasetError(f"v2 way {osm_id} references an invalid local node")
    oneway = {0: 0, 1: 1, 2: -1}[flags & 0x03]
    return RoadWay(
        osm_id=osm_id,
        highway=HIGHWAY_TYPES[highway_code],
        node_ids=tuple(node_ids),
        oneway=oneway,
        layer=layer,
        lanes=lanes,
        maxspeed_kmh=maxspeed,
        name=strings[name_id],
        ref=strings[ref_id],
        junction=strings[junction_id],
        surface=strings[surface_id],
        bridge=bool(flags & 0x04),
        tunnel=bool(flags & 0x08),
    )


def _load_v2_dataset(path: Path) -> RoadDataset:
    with Path(path).open("rb") as stream, Path(path).open("rb") as geometry_stream:
        header = _read_v2_header(stream)
        if Path(path).stat().st_size != header["file_size"]:
            raise RoadDatasetError("v2 file size does not match header")
        stream.seek(header["node_offset"])
        coordinates = [V2_NODE.unpack(_read_exact(stream, V2_NODE.size)) for _ in range(header["node_count"])]
        for index, (latitude, longitude) in enumerate(coordinates):
            if not -900_000_000 <= latitude <= 900_000_000 or not -1_800_000_000 <= longitude <= 1_800_000_000:
                raise RoadDatasetError(f"invalid v2 coordinate for local node {index}")
        strings = _read_v2_strings(stream, header)
        stream.seek(header["way_offsets_offset"])
        offsets = [UINT32.unpack(_read_exact(stream, UINT32.size))[0] for _ in range(header["way_count"] + 1)]
        if offsets != sorted(offsets) or offsets[-1] != header["geometry_offset"] - header["way_records_offset"]:
            raise RoadDatasetError("invalid v2 way-record offsets")
        ways = []
        for index in range(header["way_count"]):
            stream.seek(header["way_records_offset"] + offsets[index])
            ways.append(_read_v2_way(
                stream, geometry_stream, strings, header["node_count"],
                header["geometry_offset"], header["string_offsets_offset"],
                header["way_records_offset"] + offsets[index + 1],
            ))
        return RoadDataset(dict(enumerate(coordinates)), tuple(ways))


def _validate_v2_dataset(path: Path) -> dict[str, int]:
    path = Path(path)
    with path.open("rb") as stream, path.open("rb") as geometry_stream:
        header = _read_v2_header(stream)
        if path.stat().st_size != header["file_size"]:
            raise RoadDatasetError("v2 file size does not match header")
        stream.seek(header["node_offset"])
        for index in range(header["node_count"]):
            latitude, longitude = V2_NODE.unpack(_read_exact(stream, V2_NODE.size))
            if not -900_000_000 <= latitude <= 900_000_000 or not -1_800_000_000 <= longitude <= 1_800_000_000:
                raise RoadDatasetError(f"invalid v2 coordinate for local node {index}")
        strings = _read_v2_strings(stream, header)
        stream.seek(header["way_offsets_offset"])
        offsets = [UINT32.unpack(_read_exact(stream, UINT32.size))[0] for _ in range(header["way_count"] + 1)]
        if offsets != sorted(offsets) or offsets[-1] != header["geometry_offset"] - header["way_records_offset"]:
            raise RoadDatasetError("invalid v2 way-record offsets")
        geometry_count = 0
        for index in range(header["way_count"]):
            stream.seek(header["way_records_offset"] + offsets[index])
            way = _read_v2_way(
                stream, geometry_stream, strings, header["node_count"],
                header["geometry_offset"], header["string_offsets_offset"],
                header["way_records_offset"] + offsets[index + 1],
            )
            geometry_count += len(way.node_ids)
        if geometry_count != header["geometry_count"]:
            raise RoadDatasetError("v2 geometry count does not match header")
    return {"nodes": header["node_count"], "ways": header["way_count"], "geometry_points": geometry_count}


def load_road_dataset(path: Path) -> RoadDataset:
    version = _file_version(path)
    if version == FORMAT_VERSION:
        return _load_v1_dataset(path)
    if version == V2_FORMAT_VERSION:
        return _load_v2_dataset(path)
    raise RoadDatasetError(f"unsupported road dataset version: {version}")


def validate_road_dataset(path: Path) -> dict[str, int]:
    version = _file_version(path)
    if version == FORMAT_VERSION:
        return _validate_v1_dataset(path)
    if version == V2_FORMAT_VERSION:
        return _validate_v2_dataset(path)
    raise RoadDatasetError(f"unsupported road dataset version: {version}")


def analyze_road_binary(path: Path) -> dict:
    path = Path(path)
    version = _file_version(path)
    file_size = path.stat().st_size
    if version == FORMAT_VERSION:
        with path.open("rb") as stream:
            node_count, way_count = _read_header(stream)
            node_bytes = node_count * NODE.size
            stream.seek(node_bytes, os.SEEK_CUR)
            geometry_count = 0
            string_payload = 0
            unique_strings = set()
            for _ in range(way_count):
                _, _, _, _, _, _, _, ref_count = WAY.unpack(_read_exact(stream, WAY.size))
                geometry_count += ref_count
                stream.seek(ref_count * NODE_ID.size, os.SEEK_CUR)
                for _ in range(4):
                    size, = UINT16.unpack(_read_exact(stream, UINT16.size))
                    value = _read_exact(stream, size)
                    string_payload += size
                    unique_strings.add(value)
            if stream.tell() != file_size:
                raise RoadDatasetError("v1 analysis did not consume the complete file")
        sections = {
            "header": HEADER.size,
            "nodes": node_bytes,
            "way_metadata": way_count * WAY.size,
            "geometry_references": geometry_count * NODE_ID.size,
            "string_lengths": way_count * 4 * UINT16.size,
            "string_data": string_payload,
            "padding_other": 0,
        }
        string_count = len(unique_strings)
    elif version == V2_FORMAT_VERSION:
        with path.open("rb") as stream:
            header = _read_v2_header(stream)
        if header["file_size"] != file_size:
            raise RoadDatasetError("v2 file size does not match header")
        node_count = header["node_count"]
        way_count = header["way_count"]
        geometry_count = header["geometry_count"]
        string_count = header["string_count"]
        sections = {
            "header": V2_HEADER.size,
            "nodes": header["way_offsets_offset"] - header["node_offset"],
            "way_offsets": header["way_records_offset"] - header["way_offsets_offset"],
            "way_records": header["geometry_offset"] - header["way_records_offset"],
            "geometry_references": header["string_offsets_offset"] - header["geometry_offset"],
            "string_offsets": header["string_data_offset"] - header["string_offsets_offset"],
            "string_data": header["file_size"] - header["string_data_offset"],
            "padding_other": 0,
        }
    else:
        raise RoadDatasetError(f"unsupported road dataset version: {version}")
    if sum(sections.values()) != file_size:
        sections["padding_other"] += file_size - sum(sections.values())
    return {
        "format_version": version,
        "file": str(path.resolve()),
        "file_size": file_size,
        "node_count": node_count,
        "way_count": way_count,
        "geometry_points": geometry_count,
        "string_count": string_count,
        "sections": sections,
        "bytes_per_node": file_size / node_count,
        "bytes_per_geometry_point": file_size / geometry_count,
        "bytes_per_way": file_size / way_count,
    }


def print_binary_analysis(analysis: Mapping) -> None:
    print("=" * 40)
    print("Finland Roads Binary Format Analysis")
    print("=" * 40)
    print(f"Format version: {analysis['format_version']}")
    print(f"File size: {_format_bytes(analysis['file_size'])}")
    for name, size in analysis["sections"].items():
        print(f"{name.replace('_', ' ').title()}: {_format_bytes(size)} ({size:,} bytes)")
    print(f"Stored nodes: {analysis['node_count']:,}")
    print(f"Geometry points: {analysis['geometry_points']:,}")
    print(f"Ways: {analysis['way_count']:,}")
    print(f"Unique strings: {analysis['string_count']:,}")
    print(f"Average bytes/node: {analysis['bytes_per_node']:.2f}")
    print(f"Average bytes/geometry point: {analysis['bytes_per_geometry_point']:.2f}")
    print(f"Average bytes/way: {analysis['bytes_per_way']:.2f}")


def _v1_nodes_for_comparison(path: Path) -> tuple[dict[int, tuple[int, int]], int]:
    with Path(path).open("rb") as stream:
        node_count, way_count = _read_header(stream)
        return _read_nodes(stream, node_count), way_count


def _v1_ways(path: Path, nodes: Mapping[int, tuple[int, int]]) -> Iterator[RoadWay]:
    with Path(path).open("rb") as stream:
        node_count, way_count = _read_header(stream)
        stream.seek(node_count * NODE.size, os.SEEK_CUR)
        for _ in range(way_count):
            yield _read_way(stream, nodes)  # dict membership avoids duplicating a 10M-ID set


def _v2_comparison_data(path: Path):
    with Path(path).open("rb") as stream:
        header = _read_v2_header(stream)
        stream.seek(header["node_offset"])
        latitudes = array.array("i")
        longitudes = array.array("i")
        for _ in range(header["node_count"]):
            latitude, longitude = V2_NODE.unpack(_read_exact(stream, V2_NODE.size))
            latitudes.append(latitude)
            longitudes.append(longitude)
        strings = _read_v2_strings(stream, header)
        stream.seek(header["way_offsets_offset"])
        offsets = array.array("I")
        offsets.frombytes(_read_exact(stream, (header["way_count"] + 1) * UINT32.size))
        if sys.byteorder != "little":
            offsets.byteswap()
    return header, latitudes, longitudes, strings, offsets


def _v2_ways(path: Path, header: Mapping[str, int], strings: list[str], offsets: array.array) -> Iterator[RoadWay]:
    with Path(path).open("rb") as records, Path(path).open("rb") as geometry:
        for index in range(header["way_count"]):
            records.seek(header["way_records_offset"] + offsets[index])
            yield _read_v2_way(
                records, geometry, strings, header["node_count"],
                header["geometry_offset"], header["string_offsets_offset"],
                header["way_records_offset"] + offsets[index + 1],
            )


def compare_road_datasets(v1_path: Path, v2_path: Path) -> dict[str, int | str]:
    if _file_version(v1_path) != FORMAT_VERSION or _file_version(v2_path) != V2_FORMAT_VERSION:
        raise RoadDatasetError("semantic comparison requires a v1 file followed by a v2 file")
    v1_nodes, v1_way_count = _v1_nodes_for_comparison(v1_path)
    header, latitudes, longitudes, strings, offsets = _v2_comparison_data(v2_path)
    if len(v1_nodes) != header["node_count"] or v1_way_count != header["way_count"]:
        raise RoadDatasetError("v1/v2 node or way counts differ")

    attributes = (
        "osm_id", "highway", "oneway", "layer", "lanes", "maxspeed_kmh",
        "name", "ref", "junction", "surface", "bridge", "tunnel",
    )
    geometry_count = 0
    v1_iterator = _v1_ways(v1_path, v1_nodes)
    v2_iterator = _v2_ways(v2_path, header, strings, offsets)
    for way_index, (v1_way, v2_way) in enumerate(zip(v1_iterator, v2_iterator, strict=True)):
        for attribute in attributes:
            if getattr(v1_way, attribute) != getattr(v2_way, attribute):
                raise RoadDatasetError(
                    f"v1/v2 mismatch at way {way_index} ({v1_way.osm_id}) field {attribute}"
                )
        if len(v1_way.node_ids) != len(v2_way.node_ids):
            raise RoadDatasetError(f"v1/v2 geometry count mismatch for way {v1_way.osm_id}")
        for v1_node_id, v2_node_index in zip(v1_way.node_ids, v2_way.node_ids):
            if v1_nodes[v1_node_id] != (latitudes[v2_node_index], longitudes[v2_node_index]):
                raise RoadDatasetError(f"v1/v2 geometry mismatch for way {v1_way.osm_id}")
        geometry_count += len(v1_way.node_ids)
    if geometry_count != header["geometry_count"]:
        raise RoadDatasetError("v1/v2 total geometry counts differ")
    return {
        "ways": v1_way_count,
        "nodes": len(v1_nodes),
        "geometry_points": geometry_count,
        "validation": "PASS",
    }


def _parse_tags(encoded: str) -> dict[str, str]:
    if not encoded:
        return {}
    tags = {}
    for item in encoded.split(","):
        key, separator, value = item.partition("=")
        if separator:
            tags[unquote(key)] = unquote(value)
    return tags


def _opl_fields(line: str) -> dict[str, str]:
    return {part[0]: part[1:] for part in line.rstrip().split(" ") if part}


def _parse_positive_int(value: str, default: int) -> int:
    try:
        return max(1, int(value.split(";", 1)[0].strip()))
    except (AttributeError, TypeError, ValueError):
        return default


def _parse_oneway(tags: Mapping[str, str], highway: str) -> int:
    value = tags.get("oneway", "").casefold()
    if value in {"yes", "1", "true"}:
        return 1
    if value in {"-1", "reverse"}:
        return -1
    if value == "no":
        return 0
    return 1 if highway in {"motorway", "motorway_link"} or tags.get("junction", "").casefold() == "roundabout" else 0


DEFAULT_SPEED_LIMITS_KMH = {
    "motorway": 100, "motorway_link": 50, "trunk": 80, "trunk_link": 50,
    "primary": 80, "primary_link": 50, "secondary": 80,
    "secondary_link": 50, "tertiary": 60, "tertiary_link": 50,
    "unclassified": 50, "residential": 40, "living_street": 20,
    "service": 30, "road": 50,
}


def _parse_maxspeed(value: str, highway: str) -> int:
    tag = value.casefold().split(";", 1)[0].strip()
    numeric = tag.replace("km/h", "").replace("kph", "").replace("mph", "").strip()
    try:
        speed = float(numeric) * (1.609344 if "mph" in tag else 1.0)
        if speed > 0:
            return round(speed)
    except ValueError:
        pass
    for word, speed in (("urban", 50), ("rural", 80), ("motorway", 100), ("living_street", 20)):
        if word in tag:
            return speed
    return DEFAULT_SPEED_LIMITS_KMH[highway]


def _truthy_osm(value: str) -> bool:
    return bool(value) and value.casefold() not in {"no", "false", "0"}


def _parse_layer(value: str, bridge: bool, tunnel: bool) -> int:
    try:
        return int(value)
    except ValueError:
        return -1 if tunnel else (1 if bridge else 0)


def _road_from_opl(line: str) -> RoadWay:
    fields = _opl_fields(line)
    tags = _parse_tags(fields.get("T", ""))
    highway = tags.get("highway", "")
    node_ids = tuple(int(item[1:]) for item in fields.get("N", "").split(",") if item.startswith("n"))
    oneway = _parse_oneway(tags, highway)
    lanes_default = 2 if oneway and highway in {"motorway", "trunk"} else 1
    bridge = _truthy_osm(tags.get("bridge", ""))
    tunnel = _truthy_osm(tags.get("tunnel", ""))
    return RoadWay(
        osm_id=int(line.split(" ", 1)[0][1:]),
        highway=highway,
        node_ids=node_ids,
        oneway=oneway,
        layer=_parse_layer(tags.get("layer", ""), bridge, tunnel),
        lanes=_parse_positive_int(tags.get("lanes", ""), lanes_default),
        maxspeed_kmh=_parse_maxspeed(tags.get("maxspeed", ""), highway),
        name=tags.get("name") or tags.get("name:fi") or tags.get("name:en") or tags.get("official_name", ""),
        ref=tags.get("ref", ""),
        junction=tags.get("junction", "").casefold(),
        surface=tags.get("surface", "").casefold(),
        bridge=bridge,
        tunnel=tunnel,
    )


def _source_counts(pbf_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["osmium", "fileinfo", "-e", "--json", str(pbf_path)],
        check=True, capture_output=True, text=True,
    )
    counts = json.loads(result.stdout)["data"]["count"]
    return int(counts["nodes"]), int(counts["ways"])


def _haversine_m(first: tuple[int, int], second: tuple[int, int]) -> float:
    lat1, lon1 = (math.radians(decode_coordinate(value)) for value in first)
    lat2, lon2 = (math.radians(decode_coordinate(value)) for value in second)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12_742_000.0 * math.asin(min(1.0, math.sqrt(value)))


def _peak_memory_bytes() -> int | None:
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except (ImportError, ValueError):
        return None


def _atomic_json(path: Path, data: Mapping) -> None:
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def build_finland_roads(
    input_path: Path,
    output_path: Path,
    highway_types: frozenset[str] = DRIVABLE_HIGHWAY_TYPES,
    format_version: int = FORMAT_VERSION,
) -> dict:
    input_path, output_path = Path(input_path), Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if input_path.resolve() == output_path.resolve():
        raise RoadDatasetError("input and output paths must be different")
    if shutil.which("osmium") is None:
        raise RuntimeError("osmium-tool is required (the 'osmium' command was not found)")
    unknown = highway_types - DRIVABLE_HIGHWAY_TYPES
    if unknown:
        raise RoadDatasetError(f"highway types outside the defined whitelist: {sorted(unknown)}")
    if not highway_types:
        raise RoadDatasetError("the highway whitelist may not be empty")
    if format_version not in (FORMAT_VERSION, V2_FORMAT_VERSION):
        raise RoadDatasetError(f"unsupported output format version: {format_version}")

    started = time.perf_counter()
    input_size = input_path.stat().st_size
    total_nodes, total_ways = _source_counts(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_temp = output_path.with_name(f".{output_path.name}.tmp")
    highway_counts = Counter()
    node_coordinates: dict[int, tuple[int, int]] = {}
    geometry_points = 0
    road_length_m = 0.0
    extraction_started = time.perf_counter()

    try:
        with tempfile.TemporaryDirectory(prefix="rrt-roads-") as temporary_dir:
            filtered = Path(temporary_dir) / "drivable.osm.pbf"
            expression = "w/highway=" + ",".join(sorted(highway_types))
            subprocess.run([
                "osmium", "tags-filter", "--remove-tags",
                "-f", "pbf,add_metadata=false", "-o", str(filtered),
                str(input_path), expression,
            ], check=True)
            extraction_seconds = time.perf_counter() - extraction_started

            writing_started = time.perf_counter()
            process = subprocess.Popen(
                ["osmium", "cat", str(filtered), "-f", "opl", "-o", "-"],
                stdout=subprocess.PIPE, text=True, encoding="utf-8",
            )
            assert process.stdout is not None
            output_stream = None
            if format_version == FORMAT_VERSION:
                output_stream = output_temp.open("w+b")
                writer = RoadDatasetWriter(output_stream)
            else:
                writer = V2DatasetWriter(Path(temporary_dir))
            try:
                for line in process.stdout:
                    if line.startswith("n"):
                        fields = _opl_fields(line)
                        node_id = int(line.split(" ", 1)[0][1:])
                        latitude = encode_coordinate(float(fields["y"]))
                        longitude = encode_coordinate(float(fields["x"]))
                        if format_version == FORMAT_VERSION:
                            node_coordinates[node_id] = (latitude, longitude)
                        writer.write_node(node_id, latitude, longitude)
                    elif line.startswith("w"):
                        way = _road_from_opl(line)
                        if way.highway not in highway_types:
                            raise RoadDatasetError(f"unexpected highway type in filtered data: {way.highway}")
                        if format_version == FORMAT_VERSION:
                            missing = next((node_id for node_id in way.node_ids if node_id not in node_coordinates), None)
                            if missing is not None:
                                raise RoadDatasetError(f"way {way.osm_id} references missing node {missing}")
                            for first, second in zip(way.node_ids, way.node_ids[1:]):
                                road_length_m += _haversine_m(node_coordinates[first], node_coordinates[second])
                        geometry_points += len(way.node_ids)
                        highway_counts[way.highway] += 1
                        writer.write_way(way)
                return_code = process.wait()
                if return_code:
                    raise RuntimeError(f"osmium cat failed with exit code {return_code}")
                if format_version == FORMAT_VERSION:
                    writer.finish()
                else:
                    writer.finish(output_temp)
                    road_length_m = writer.road_length_m
            finally:
                if output_stream is not None:
                    output_stream.close()
                if isinstance(writer, V2DatasetWriter):
                    writer.close()
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            writing_seconds = time.perf_counter() - writing_started

        node_coordinates.clear()
        validation_started = time.perf_counter()
        validation = validate_road_dataset(output_temp)
        validation_seconds = time.perf_counter() - validation_started
        output_temp.replace(output_path)
    finally:
        output_temp.unlink(missing_ok=True)

    output_size = output_path.stat().st_size
    processing_seconds = time.perf_counter() - started
    stats = {
        "format_version": format_version,
        "input_pbf": str(input_path.resolve()),
        "output_bin": str(output_path.resolve()),
        "input_file_size": input_size,
        "output_file_size": output_size,
        "size_reduction_percent": round((1.0 - output_size / input_size) * 100.0, 3),
        "bin_to_pbf_percent": round(output_size / input_size * 100.0, 3),
        "total_ways": total_ways,
        "drivable_ways": validation["ways"],
        "ignored_ways": total_ways - validation["ways"],
        "total_nodes": total_nodes,
        "stored_nodes": validation["nodes"],
        "geometry_points": geometry_points,
        "road_length_m": round(road_length_m, 3),
        "highway_types": {name: highway_counts[name] for name in sorted(highway_types)},
        "extraction_seconds": round(extraction_seconds, 3),
        "binary_writing_seconds": round(writing_seconds, 3),
        "validation_seconds": round(validation_seconds, 3),
        "processing_seconds": round(processing_seconds, 3),
        "peak_memory_bytes": _peak_memory_bytes(),
        "validation": "PASS",
    }
    _atomic_json(output_path.with_suffix(".stats.json"), stats)
    return stats


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unavailable"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.2f} {unit}"
        size /= 1024.0
    raise AssertionError


def print_report(stats: Mapping) -> None:
    print("=" * 40)
    print(f"Road Rage Taxi Finland Road Dataset v{stats['format_version']}")
    print("=" * 40)
    print(f"Input PBF: {stats['input_pbf']}")
    print(f"Input size: {_format_bytes(stats['input_file_size'])}")
    print(f"Output: {stats['output_bin']}")
    print(f"Output size: {_format_bytes(stats['output_file_size'])}")
    print(f"Reduction: {stats['size_reduction_percent']:.1f} %")
    print(f"BIN / PBF: {stats['bin_to_pbf_percent']:.2f} %")
    print(f"Ways inspected: {stats['total_ways']:,}")
    print(f"Drivable ways: {stats['drivable_ways']:,}")
    print(f"Ignored ways: {stats['ignored_ways']:,}")
    print(f"Nodes encountered: {stats['total_nodes']:,}")
    print(f"Nodes stored: {stats['stored_nodes']:,}")
    print(f"Geometry points: {stats['geometry_points']:,}")
    print(f"Road length: {stats['road_length_m'] / 1000:,.1f} km")
    print("Highway breakdown:")
    for highway, count in stats["highway_types"].items():
        print(f"  {highway}: {count:,}")
    print(f"Extraction time: {stats['extraction_seconds']:.1f} s")
    print(f"Binary writing: {stats['binary_writing_seconds']:.1f} s")
    print(f"Validation: {stats['validation_seconds']:.1f} s")
    print(f"Total processing time: {stats['processing_seconds']:.1f} s")
    print(f"Peak memory: {_format_bytes(stats['peak_memory_bytes'])}")
    print(f"Validation: {stats['validation']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Input .osm.pbf")
    parser.add_argument("--output", type=Path, help="Output .bin")
    parser.add_argument("--format-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--analyze", type=Path, help="Analyze an existing v1 or v2 binary and exit")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("V1", "V2"), help="Semantically compare v1 and v2 binaries")
    parser.add_argument(
        "--highway-types",
        default=",".join(sorted(DRIVABLE_HIGHWAY_TYPES)),
        help="Comma-separated subset of the defined drivable highway whitelist",
    )
    args = parser.parse_args()
    try:
        if args.analyze:
            print_binary_analysis(analyze_road_binary(args.analyze))
            return 0
        if args.compare:
            comparison = compare_road_datasets(*args.compare)
            print(
                "Semantic comparison: PASS "
                f"({comparison['ways']:,} ways, {comparison['nodes']:,} nodes, "
                f"{comparison['geometry_points']:,} geometry points)"
            )
            return 0
        if args.input is None or args.output is None:
            parser.error("--input and --output are required unless --analyze or --compare is used")
        stats = build_finland_roads(
            args.input,
            args.output,
            frozenset(value.strip() for value in args.highway_types.split(",") if value.strip()),
            args.format_version,
        )
    except (OSError, RoadDatasetError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_report(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
