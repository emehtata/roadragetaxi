You are implementing a minimal proof-of-concept game in VS Code with Python + Pygame.

Project name: The Road Rage Trip
Goal: top-down 2D driving where the road network follows real-world OpenStreetMap data (Finland), while scenery can remain simple/procedural.

Tech:
- Python 3.10+
- pygame
- requests
- pyproj (use EPSG:3067 ETRS-TM35FIN, meters)
No heavy dependencies besides those.

Functional requirements:
1) Map data
- Fetch OSM “highway” ways from Overpass API for a configurable bounding box (south, west, north, east in lat/lon).
- Also support offline runs: cache the Overpass JSON to a local file (e.g., data/osm_cache.json) and load from it if present.
- Parse nodes and ways; keep a list of road polylines (list of (x_m, y_m) points).
- Keep tags: highway type, oneway if present, maxspeed if present (optional).
- Infer road half-width meters by highway type with a dict of defaults (motorway > residential > track etc).

2) Projection
- Convert lon/lat -> meters using pyproj Transformer from EPSG:4326 to EPSG:3067 with always_xy=True.

3) Rendering
- Render background (solid grass color).
- Render roads as thick polylines (pygame.draw.lines) with thickness = width_m * pixels_per_meter.
- Camera is centered on the car; world coordinates are meters, screen coordinates are pixels.

4) Vehicle
- Simple arcade physics:
  - speed, heading
  - throttle/brake/friction
  - steering that becomes less sensitive at higher speed
  - clamp max forward speed
- Controls: WASD + arrow keys.

5) On-road detection (PoC)
- Implement distance from car point to line segments of nearby roads.
- For PoC you may brute-force for small bbox; but structure code so it can later use spatial indexing.
- Show HUD: speed km/h and “On road: YES/NO”.

Non-functional requirements:
- Must run with `python -m road_rage_trip` or `python road_rage_trip.py`.
- Organize into modules after initial working single-file:
  - src/road_rage_trip/main.py
  - src/road_rage_trip/osm.py (fetch/cache/parse)
  - src/road_rage_trip/geo.py (projection, geometry helpers)
  - src/road_rage_trip/render.py
  - src/road_rage_trip/physics.py
- Provide requirements.txt and README.md with setup and controls.
- Use type hints, dataclasses, and keep code readable.
- Add constants/config for bbox, FPS, window size, pixels_per_meter.

Milestones (implement in this order):
A) Single-file runnable: fetch OSM, project, draw roads, drive car.
B) Add caching to disk.
C) Refactor into modules with a minimal package structure.
D) Add an option to switch bbox (Helsinki vs Oulu) via config or CLI args.

When uncertain, prefer the simplest solution that produces a visible working PoC quickly.
