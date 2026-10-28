"""Bind electronic signs to directed, connected OSM approaches using road-register geometry."""
import math

REFERENCE_URL = 'https://avoinapi.vaylapilvi.fi/viitekehysmuunnin/muunna'
MATCH_M = 15.0
MAX_SEGMENTS = 128  # shortcut: hide beyond this budget; cache graph walks if dense maps need longer approaches


def reference_direction(client, sign, day):
    """Väylä supplies an increasing-address baseline in EPSG:3067, independent of OSM order."""
    if sign['direction'] not in ('INCREASING', 'DECREASING'):
        return None
    carriageway = {'SINGLE': 0, 'RIGHT': 1, 'LEFT': 2}.get(sign.get('carriageway'))
    if carriageway is None:
        return None
    road, section, distance = sign['road_address']
    data = client.get_json(REFERENCE_URL, {'tie': road, 'ajorata': carriageway, 'osa': section,
        'etaisyys': max(0, distance - 10), 'osa_loppu': section, 'etaisyys_loppu': distance + 10,
        'valihaku': 'true', 'tilannepvm': day.strftime('%d.%m.%Y'), 'kohdepvm': day.strftime('%d.%m.%Y')})
    matches = []
    features = data.get('features') if isinstance(data, dict) else None
    if not isinstance(features, list):
        return None
    for feature in features:
        try:
            p = feature['properties']
            if (p.get('virheet') or p['tie'] != road or p['osa'] != section or p['ajorata'] != carriageway
                    or p['osa_loppu'] != section or p['etaisyys_loppu'] <= p['etaisyys']
                    or p.get('vertikaalisuhde', 0) != 0 or p.get('vertikaalisuhde_loppu', 0) != 0):
                continue
            a, b = (p['x'], p['y']), (p['x_loppu'], p['y_loppu'])
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (*a, *b)):
                continue
            if not 1 <= math.dist(a, b) <= 40:
                continue
            if sign['direction'] == 'DECREASING':
                a, b = b, a
            matches.append((a, b))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return matches[0] if len(matches) == 1 else None


def _roads(way):
    return {r.strip() for r in str(getattr(way, 'ref', '') or '').replace(',', ';').split(';')}


def _surface(way):
    return (getattr(way, 'is_drivable', False) and getattr(way, 'layer', 0) == 0
            and getattr(way, 'map_level', None) in (None, 0))


def _projection(a, b, point):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    t = max(0, min(1, ((point[0]-a[0])*dx + (point[1]-a[1])*dy) / length_sq)) if length_sq else 0
    return t, (a[0] + dx*t, a[1] + dy*t)


def bind_sign(sign, grid):
    baseline = sign.get('_direction_line')
    if grid is None or baseline is None:
        return None
    a, b = baseline
    centre = ((a[0]+b[0])/2, (a[1]+b[1])/2)
    if math.dist(centre, (sign['x'], sign['y'])) > 40:
        return None  # stale road address or a mismatched provider location
    bearing = math.atan2(b[1]-a[1], b[0]-a[0])
    candidates = []
    for way in grid.ways_in_rect(centre[0]-MATCH_M, centre[1]-MATCH_M, centre[0]+MATCH_M, centre[1]+MATCH_M):
        if not _surface(way) or sign['road'] not in _roads(way):
            continue
        for index, (p, q) in enumerate(zip(way.points_m, way.points_m[1:])):
            if math.dist(p, q) < 0.01:
                continue
            alignment = math.cos(math.atan2(q[1]-p[1], q[0]-p[0]) - bearing)
            if abs(alignment) < math.cos(math.radians(30)):
                continue
            step = 1 if alignment > 0 else -1
            if way.oneway not in (0, step):
                continue
            fraction, projected = _projection(p, q, centre)
            distance = math.dist(centre, projected)
            if distance <= MATCH_M:
                candidates.append((distance, way, index, step, fraction))
    candidates.sort(key=lambda c: c[0])
    if not candidates:
        return None
    best = candidates[0]
    # Adjacent segments of the same way may meet at the sign; separate roads must be unambiguous.
    if any(c[1] is not best[1] and c[0] <= best[0] + 0.5 for c in candidates[1:]):
        return None
    return best[1:]


def approach(car, way, grid, distance_m, node_cache=None):
    """Walk forward along unambiguous same-road segments; no routing guess at a fork."""
    if grid is None or not _surface(way):
        return []
    point = car.x, car.y
    candidates = []
    for i, (a,b) in enumerate(zip(way.points_m, way.points_m[1:])):
        t, projected = _projection(a,b,point)
        candidates.append((math.dist(point,projected), i, t))
    if not candidates:
        return []
    lateral, index, fraction = min(candidates)
    if lateral > way.half_width_m + 2:
        return []
    a,b = way.points_m[index:index+2]
    travel = car.heading + (math.pi if car.speed < 0 else 0)
    alignment = math.cos(travel - math.atan2(b[1]-a[1],b[0]-a[0]))
    if abs(alignment) < math.cos(math.radians(45)):
        return []
    step = 1 if alignment > 0 else -1
    if way.oneway not in (0, step):
        return []
    roads = {r for r in _roads(way) if r.isdigit()}
    node_cache = {} if node_cache is None else node_cache
    result, seen = [], set()
    covered = 0.0
    for _ in range(MAX_SEGMENTS):
        key = (id(way), index, step)
        if key in seen:
            break
        seen.add(key)
        a,b = way.points_m[index:index+2]
        length = math.dist(a,b)
        result.append((way, index, step, fraction, covered))
        covered += length * ((1-fraction) if step == 1 else fraction)
        if covered >= distance_m:
            break
        node = b if step == 1 else a
        exits = {}
        for other in grid.ways_in_rect(node[0]-0.05,node[1]-0.05,node[0]+0.05,node[1]+0.05):
            if not _surface(other) or not roads.intersection(_roads(other)):
                continue
            if id(other) not in node_cache:
                nodes = {}
                for j,p in enumerate(other.points_m):
                    nodes.setdefault((math.floor(p[0]*10),math.floor(p[1]*10)),[]).append(j)
                node_cache[id(other)] = nodes
            nx,ny = math.floor(node[0]*10),math.floor(node[1]*10)
            indices = [j for dx in (-1,0,1) for dy in (-1,0,1)
                       for j in node_cache[id(other)].get((nx+dx,ny+dy),())]
            for j in indices:
                p = other.points_m[j]
                if math.dist(node,p) > 0.05:
                    continue
                for direction in (-1,1):
                    end = j+direction
                    if not 0 <= end < len(other.points_m) or other.oneway not in (0,direction):
                        continue
                    segment = min(j,end)
                    if other is way and segment == index:
                        continue
                    if math.dist(p,other.points_m[end]) < 0.01:
                        continue
                    exits[(id(other),segment,direction)] = (other,segment,direction)
        if len(exits) != 1:
            break
        way,index,step = next(iter(exits.values()))
        fraction = 0.0 if step == 1 else 1.0
    return result


def distance_on_approach(binding, path):
    if binding is None:
        return None
    way,index,step,fraction = binding
    for road,segment,direction,start,covered in path:
        if road is way and segment == index and direction == step and (fraction-start)*step >= 0:
            return covered + abs(fraction-start) * math.dist(*way.points_m[index:index+2])
    return None
