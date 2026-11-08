"""What E does on foot here (fps-3d-view spec, phase 3): one place that
picks the interaction, for the prompt (state.interaction) and again for the
press, so the server validates what the client offered. Nearest kind first:
the taxi's driver's door, an enterable house's front door, a building to
inspect. Add a kind here, in its priority, with its press in the server."""
from .geo import dist_point_to_segment
from .simulation import driver_door_available

INSPECT_REACH_M = 2.5  # a building's wall within this: "E look at the building"


def building_in_reach(grid, x: float, y: float, reach: float = INSPECT_REACH_M):
    """The surface building whose wall is nearest within `reach` of (x, y), or None."""
    best, best_d = None, reach
    for building in grid.ways_in_rect(x - reach, y - reach, x + reach, y + reach):
        if getattr(building, "map_level", None) not in (None, 0):
            continue
        points = building.points_m
        for a, b in zip(points, points[1:] + points[:1]):
            d = dist_point_to_segment(x, y, a[0], a[1], b[0], b[1])
            if d <= best_d:
                best, best_d = building, d
    return best


def describe_building(building) -> str:
    """Its name and address, as mapped; "" when it has neither (the prompt says "the building")."""
    address = " ".join(part for part in (building.street, building.housenumber) if part)
    return ", ".join(part for part in (building.name, address) if part)


def pick(car, player_pedestrian, house_door: bool, grid) -> dict:
    """{"kind": "taxi_door" | "house_door" | "building", "label"?: str}, or {} for nothing in reach."""
    if driver_door_available(car, player_pedestrian):
        return {"kind": "taxi_door"}
    if house_door:
        return {"kind": "house_door"}
    building = None if grid is None else building_in_reach(grid, player_pedestrian.x, player_pedestrian.y)
    return {"kind": "building", "label": describe_building(building)} if building is not None else {}
