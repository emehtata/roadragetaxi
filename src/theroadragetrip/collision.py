"""Collision categories and the shared pair filter (docs/specs/collision-detection.md)."""
from enum import IntFlag

from .map_level import SURFACE_LEVEL


class Category(IntFlag):
    VEHICLE = 1
    PEDESTRIAN = 2
    ANIMAL = 4
    BUILDING = 8
    POST = 16
    BARRIER = 32
    ROADWORKS = 64
    NONSOLID = 128


_SOLID = Category.VEHICLE | Category.PEDESTRIAN | Category.ANIMAL | Category.BUILDING | Category.POST \
    | Category.BARRIER | Category.ROADWORKS
_NONE = Category(0)
COLLIDES: dict[Category, Category] = {
    Category.VEHICLE: _SOLID,
    Category.PEDESTRIAN: Category.VEHICLE | Category.BUILDING | Category.BARRIER,
    Category.ANIMAL: Category.VEHICLE,
    Category.BUILDING: Category.VEHICLE | Category.PEDESTRIAN,
    Category.POST: Category.VEHICLE,
    Category.BARRIER: Category.VEHICLE | Category.PEDESTRIAN,
    Category.ROADWORKS: Category.VEHICLE,
    Category.NONSOLID: _NONE,
}


def can_collide(a: Category, b: Category) -> bool:
    return bool(COLLIDES[a] & b)


def same_plane(a, b) -> bool:
    """Both bodies share the OSM `layer` and logical `map_level` (missing = surface)."""
    return (getattr(a, "layer", 0) == getattr(b, "layer", 0)
            and getattr(a, "map_level", SURFACE_LEVEL) == getattr(b, "map_level", SURFACE_LEVEL))
