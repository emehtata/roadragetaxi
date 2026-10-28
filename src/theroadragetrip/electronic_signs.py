"""Digitraffic sign readings for the nearby-sign HUD, not traffic-control decisions."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

SIGN_DISTANCE_M = 700.0
WARNING_TEXT = {'133': 'Congestion', '141': 'Uneven road', '142': 'Road works', '143': 'Loose gravel',
                '144': 'Slippery road', '147': 'Dangerous shoulder', '154': 'Ski track',
                '155': 'Elk', '156': 'Reindeer', '165': 'Traffic lights', '183': 'Crosswind', '189': 'Other danger'}


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Sign timestamps must have a timezone')
    return parsed.astimezone(timezone.utc)


def parse_signs(collection):
    """Validate public GeoJSON before anything reaches the simulation or UI."""
    signs = []
    if not isinstance(collection, dict) or not isinstance(collection.get('features'), list):
        return signs
    for feature in collection['features']:
        try:
            props, geometry = feature['properties'], feature['geometry']
            if geometry['type'] != 'Point' or props.get('reliability') != 'NORMAL':
                continue
            lon, lat = geometry['coordinates'][:2]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lon, lat)):
                continue
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            kind, ident = props['type'], props['id']
            if kind not in ('SPEEDLIMIT', 'WARNING', 'INFORMATION') or not isinstance(ident, str):
                continue
            road = str(props['roadAddress']).split()[0]
            if not road.isdigit():
                continue
            effect = props['effectDate']
            _time(effect)
            value = props.get('displayValue', '')
            rows = props.get('textRows', [])
            if not isinstance(rows, list) or not isinstance(value, str):
                continue
            text = []
            for row in sorted(rows, key=lambda r: (r.get('screen', 1), r.get('rowNumber', 0))):
                if row.get('screen', 1) != 1 or not isinstance(row.get('text'), str):
                    continue
                line = row['text'].strip()
                try:
                    line = line.encode('latin1').decode('utf8')
                except (UnicodeError, ValueError):
                    pass
                if line:
                    text.append(line)
            speed = int(value) if kind == 'SPEEDLIMIT' and value.isdigit() else None
            if kind == 'SPEEDLIMIT' and value and (speed is None or not 10 <= speed <= 130):
                continue
            signs.append({'id': ident, 'type': kind, 'road': road, 'lon': lon, 'lat': lat,
                          'effect_date': effect, 'speed_limit_kmh': speed, 'code': value if kind != 'SPEEDLIMIT' else '',
                          'text': text, 'direction': props.get('direction', ''), '_effect_time': _time(effect).timestamp()})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue
    return signs


def fetch_signs(client, tiles, start):
    from .digitraffic_road import WINDOW_MIN, tile_of

    data = client.get_json('/api/variable-sign/v1/signs', max_age_s=60)
    if not isinstance(data, dict) or not isinstance(data.get('features'), list):
        return [], False
    # Retain blank latest values as history metadata; parsing hides blank displays later.
    features = []
    complete = True
    for feature in data.get('features', []):
        try:
            props = feature['properties']
            lon, lat = feature['geometry']['coordinates'][:2]
            if tile_of(lon, lat) not in tiles:
                continue
            if _time(props['effectDate']) <= start:
                features.append(feature)
                continue
            history = client.get_json('/api/variable-sign/v1/signs/history',
                                      {'deviceId': props['id'], 'effectiveDate': start.date().isoformat()},
                                      max_age_s=60 if start.date() == datetime.now(timezone.utc).date() else None)
            complete &= history is not None
            for reading in history if isinstance(history, list) else []:
                merged = dict(props, displayValue=reading.get('displayValue', ''),
                              effectDate=reading['effectDate'], textRows=reading.get('rows', []))
                features.append(dict(feature, properties=merged))
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError):
            continue
    # Keep only the starting reading and changes in this window, not a whole day's history per tick.
    previous, changes = {}, []
    end = (start + timedelta(minutes=WINDOW_MIN)).timestamp()
    for sign in parse_signs({'features': features}):
        when = sign['_effect_time']
        if when <= start.timestamp():
            if sign['id'] not in previous or when > previous[sign['id']]['_effect_time']:
                previous[sign['id']] = sign
        elif when <= end:
            changes.append(sign)
    return list(previous.values()) + changes, complete


def nearby_signs(signs, car, way, moment):
    """Nearby same-road readings, explicitly informational: direction is not inferred."""
    if way is None or getattr(car, 'layer', 0) != 0 or getattr(car, 'map_level', 0) != 0:
        return []
    roads = {r.strip() for r in str(getattr(way, 'ref', '') or '').replace(',', ';').split(';')}
    now = moment.timestamp()
    newest = {}
    for sign in signs:
        if sign['road'] not in roads or sign['_effect_time'] > now:
            continue
        if sign['id'] not in newest or sign['_effect_time'] > newest[sign['id']]['_effect_time']:
            newest[sign['id']] = sign
    rows = []
    for sign in newest.values():
        if sign['speed_limit_kmh'] is None and not sign['code'] and not sign['text']:
            continue
        distance = math.hypot(sign['x'] - car.x, sign['y'] - car.y)
        if distance <= SIGN_DISTANCE_M:
            rows.append({k: v for k, v in dict(sign, distance_m=round(distance / 10) * 10).items()
                         if k not in ('x', 'y', 'lon', 'lat', '_effect_time')})
    rows.sort(key=lambda s: (s['distance_m'], s['id']))
    selected = {}
    for row in rows:
        selected.setdefault(row['type'], row)
    return list(selected.values())
