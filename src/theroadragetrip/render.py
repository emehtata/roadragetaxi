import math
from typing import List, Optional

from .geo import clip_polygon_to_rect, meters_to_latlon
from .osm import Building, Place, Scenery, Water, Way
from .physics import Car
from .taxi import TaxiManager, TaxiState

SCREEN_W, SCREEN_H = 1280, 720
FPS = 60
PX_PER_M = 0.7  # Default zoom level (pixels per meter)


def world_to_screen(
    wx: float,
    wy: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> tuple[int, int]:
    """Convert world meters -> screen pixels with north-up orientation."""
    sx = (wx - camx) * px_per_m + screen_w / 2
    sy = screen_h / 2 - (wy - camy) * px_per_m
    return int(sx), int(sy)


def world_to_screen(
    wx: float,
    wy: float,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> tuple[int, int]:
    """Convert world meters -> screen pixels with north-up orientation."""
    sx = (wx - camx) * px_per_m + screen_w / 2
    sy = screen_h / 2 - (wy - camy) * px_per_m
    return int(sx), int(sy)


def get_viewport_bounds(
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    margin_m: float = 60.0,
) -> tuple[float, float, float, float]:
    """Calculate world coordinates (minx, miny, maxx, maxy) visible in the viewport."""
    half_w = (screen_w / 2.0) / px_per_m + margin_m
    half_h = (screen_h / 2.0) / px_per_m + margin_m
    return camx - half_w, camy - half_h, camx + half_w, camy + half_h


def draw_scenery(
    screen,
    sceneries: List[Scenery],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw parks, forests, and green spaces intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    colors = {
        "forest": (32, 95, 32),
        "wood": (32, 95, 32),
        "park": (42, 120, 42),
        "garden": (45, 125, 45),
        "meadow": (38, 110, 38),
        "grass": (36, 105, 36),
        "pitch": (48, 115, 55),
        "playground": (48, 115, 55),
        "sand": (160, 150, 110),
        "beach": (170, 160, 115),
    }

    for sc in sceneries:
        bb = getattr(sc, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(sc.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in sc.points_m]
        color = colors.get(sc.kind.lower(), (38, 105, 38))
        pygame.draw.polygon(screen, color, pts)


def draw_waters(
    screen,
    waters: List[Water],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw water polygons and waterways intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 80.0)

    for w in waters:
        bb = getattr(w, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue

        is_closed = len(w.points_m) >= 4 and w.points_m[0] == w.points_m[-1]
        if w.is_polygon and is_closed and len(w.points_m) >= 3:
            # Clip large water polygons to viewport to avoid software scanline lag
            if len(w.points_m) > 40:
                clipped = clip_polygon_to_rect(w.points_m, vminx, vminy, vmaxx, vmaxy)
                if len(clipped) < 3:
                    continue
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in clipped]
            else:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
            pygame.draw.polygon(screen, (30, 100, 200), pts)
            pygame.draw.lines(screen, (20, 80, 160), True, pts, 1)
        else:
            if len(w.points_m) >= 2:
                pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
                pygame.draw.lines(screen, (30, 100, 200), False, pts, max(2, int(3 * px_per_m)))


def draw_buildings(
    screen,
    buildings: List[Building],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw building footprints intersecting viewport."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 50.0)

    for b in buildings:
        bb = getattr(b, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(b.points_m) < 3:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in b.points_m]
        pygame.draw.polygon(screen, (130, 125, 120), pts)
        pygame.draw.lines(screen, (85, 80, 75), True, pts, 1)


def draw_ways(
    screen,
    ways: List[Way],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw road ways intersecting viewport with highway-type proportional thickness."""
    import pygame

    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 60.0)

    for w in ways:
        bb = getattr(w, "bbox", None)
        if bb and bb != (0.0, 0.0, 0.0, 0.0):
            if bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy:
                continue
        if len(w.points_m) < 2:
            continue
        pts = [world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h) for (x, y) in w.points_m]
        thickness = max(1, int(w.half_width_m * 2 * px_per_m))

        if not w.is_drivable:
            # Non-drivable / forbidden paths (cycleways, footways, pedestrian, private/no-access roads)
            road_color = (190, 190, 190)
            center_color = (220, 220, 220)
        elif w.is_ice_road:
            road_color = (160, 200, 225)
            center_color = (210, 235, 250)
        else:
            # Regular drivable car roads
            road_color = (70, 70, 70)
            center_color = (110, 110, 110)

        pygame.draw.lines(screen, road_color, False, pts, thickness)
        if thickness >= 6:
            pygame.draw.lines(screen, center_color, False, pts, 1)


def draw_labels(
    screen,
    font,
    ways: List[Way],
    waters: List[Water],
    buildings: List[Building],
    sceneries: List[Scenery],
    places: List[Place],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw text labels and street names with decluttering and collision avoidance."""
    import pygame

    placed_rects: List[pygame.Rect] = []
    seen_names: set[str] = set()
    vminx, vminy, vmaxx, vmaxy = get_viewport_bounds(camx, camy, px_per_m, screen_w, screen_h, 100.0)

    district_font = font
    try:
        district_font = pygame.font.SysFont(None, 28, bold=True)
    except Exception:
        pass

    def render_label(
        text: str,
        wx: float,
        wy: float,
        text_color,
        bg_color=(20, 20, 20, 190),
        use_font=None,
        border_color=None,
    ) -> bool:
        if not (vminx <= wx <= vmaxx and vminy <= wy <= vmaxy):
            return False

        sx, sy = world_to_screen(wx, wy, camx, camy, px_per_m, screen_w, screen_h)
        # Avoid HUD / top bar area
        if not (10 <= sx <= screen_w - 10 and 80 <= sy <= screen_h - 20):
            return False

        f = use_font or font
        txt_surf = f.render(text, True, text_color)
        rect = txt_surf.get_rect(center=(sx, sy))
        bg_rect = rect.inflate(10, 6)

        # Check collision with already placed labels
        for pr in placed_rects:
            if bg_rect.colliderect(pr):
                return False

        placed_rects.append(bg_rect)
        bg_surface = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surface.fill(bg_color)
        screen.blit(bg_surface, bg_rect.topleft)
        if border_color:
            pygame.draw.rect(screen, border_color, bg_rect, width=1, border_radius=3)
        screen.blit(txt_surf, rect)
        return True

    # 1. Kaupunginosat / Districts & Suburbs (high prominence, warm gold/amber)
    for p in places:
        if p.name and p.name not in seen_names:
            if render_label(
                p.name.upper(),
                p.x,
                p.y,
                (255, 230, 120),
                (30, 25, 10, 220),
                use_font=district_font,
                border_color=(200, 170, 70),
            ):
                seen_names.add(p.name)

    # 2. Water bodies (cyan)
    for wat in waters:
        if wat.name and wat.name not in seen_names and wat.points_m:
            bb = getattr(wat, "bbox", None)
            if bb and (bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy):
                continue
            cx = sum(p[0] for p in wat.points_m) / len(wat.points_m)
            cy = sum(p[1] for p in wat.points_m) / len(wat.points_m)
            if render_label(wat.name, cx, cy, (160, 225, 255), (10, 30, 50, 210)):
                seen_names.add(wat.name)

    # 3. Scenery / Parks (green)
    for sc in sceneries:
        if sc.name and sc.name not in seen_names and sc.points_m:
            bb = getattr(sc, "bbox", None)
            if bb and (bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy):
                continue
            cx = sum(p[0] for p in sc.points_m) / len(sc.points_m)
            cy = sum(p[1] for p in sc.points_m) / len(sc.points_m)
            if render_label(sc.name, cx, cy, (190, 255, 190), (15, 45, 15, 210)):
                seen_names.add(sc.name)

    # 4. Buildings (warm yellow, only when sufficiently zoomed in)
    if px_per_m >= 0.4:
        for b in buildings:
            if b.name and b.name not in seen_names and b.points_m:
                bb = getattr(b, "bbox", None)
                if bb and (bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy):
                    continue
                cx = sum(p[0] for p in b.points_m) / len(b.points_m)
                cy = sum(p[1] for p in b.points_m) / len(b.points_m)
                if render_label(b.name, cx, cy, (255, 240, 180), (35, 30, 25, 210)):
                    seen_names.add(b.name)

    # 5. Road / street names (white, only when sufficiently zoomed in)
    if px_per_m >= 0.35:
        for w in ways:
            if w.name and w.name not in seen_names and len(w.points_m) >= 2:
                bb = getattr(w, "bbox", None)
                if bb and (bb[2] < vminx or bb[0] > vmaxx or bb[3] < vminy or bb[1] > vmaxy):
                    continue
                mid_idx = len(w.points_m) // 2
                p1 = w.points_m[mid_idx - 1]
                p2 = w.points_m[mid_idx]
                mx = (p1[0] + p2[0]) / 2
                my = (p1[1] + p2[1]) / 2
                if render_label(w.name, mx, my, (255, 255, 255), (25, 25, 25, 210)):
                    seen_names.add(w.name)


def draw_car(
    screen,
    car: Car,
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw red triangular car aligned with its heading."""
    import pygame

    cx, cy = world_to_screen(car.x, car.y, camx, camy, px_per_m, screen_w, screen_h)
    size = 10
    ang = car.heading
    p1 = (cx + math.cos(ang) * size, cy - math.sin(ang) * size)
    p2 = (cx + math.cos(ang + 2.6) * size * 0.8, cy - math.sin(ang + 2.6) * size * 0.8)
    p3 = (cx + math.cos(ang - 2.6) * size * 0.8, cy - math.sin(ang - 2.6) * size * 0.8)
    pygame.draw.polygon(screen, (220, 40, 40), [p1, p2, p3])


def draw_taxi_target(
    screen,
    taxi_mgr: TaxiManager,
    camx: float,
    camy: float,
    font,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw pulsing waypoint circle, pin icon, and on-screen navigation arrow for active pickup/dropoff."""
    import pygame

    target = taxi_mgr.get_current_target()
    if not target:
        return

    is_pickup = taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP
    main_color = (255, 200, 0) if is_pickup else (50, 220, 100)
    bg_marker_color = (255, 200, 0, 70) if is_pickup else (50, 220, 100, 70)

    # World position to screen
    sx, sy = world_to_screen(target.x, target.y, camx, camy, px_per_m, screen_w, screen_h)

    # Check if target is inside screen viewport
    in_view = 30 <= sx <= screen_w - 30 and 30 <= sy <= screen_h - 30

    if in_view:
        # Draw radius zone
        rad_px = max(8, int(target.radius_m * px_per_m))
        rad_surf = pygame.Surface((rad_px * 2 + 4, rad_px * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(rad_surf, bg_marker_color, (rad_px + 2, rad_px + 2), rad_px)
        pygame.draw.circle(rad_surf, main_color, (rad_px + 2, rad_px + 2), rad_px, 2)
        screen.blit(rad_surf, (sx - rad_px - 2, sy - rad_px - 2))

        # Center pulsing marker
        pygame.draw.circle(screen, main_color, (sx, sy), 7)
        pygame.draw.circle(screen, (20, 20, 20), (sx, sy), 7, 2)

        # Label above target
        tag_text = "PICKUP" if is_pickup else "DROPOFF"
        lbl_surf = font.render(f"[{tag_text}] {target.address}", True, (255, 255, 255))
        rect = lbl_surf.get_rect(center=(sx, sy - rad_px - 14))
        bg_rect = rect.inflate(8, 4)
        bg = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 220))
        screen.blit(bg, bg_rect.topleft)
        pygame.draw.rect(screen, main_color, bg_rect, width=1, border_radius=3)
        screen.blit(lbl_surf, rect)
    else:
        # Off-screen direction indicator arrow pointing towards target
        dx = target.x - camx
        dy = target.y - camy
        angle = math.atan2(dy, dx)
        dist_m = math.hypot(dx, dy)

        # Screen margin clamp for arrow
        edge_margin = 65
        center_x = screen_w / 2
        center_y = screen_h / 2
        # Ray-intersect with screen bounding rectangle
        dir_x = math.cos(angle)
        dir_y = -math.sin(angle)  # Inverted Y for screen coords

        max_dx = (screen_w / 2) - edge_margin
        max_dy = (screen_h / 2) - edge_margin

        scale_x = abs(max_dx / dir_x) if dir_x != 0 else float("inf")
        scale_y = abs(max_dy / dir_y) if dir_y != 0 else float("inf")
        scale = min(scale_x, scale_y)

        arrow_x = int(center_x + dir_x * scale)
        arrow_y = int(center_y + dir_y * scale)

        # Draw arrow triangle
        a_len = 16
        p1 = (arrow_x + math.cos(angle) * a_len, arrow_y - math.sin(angle) * a_len)
        p2 = (arrow_x + math.cos(angle + 2.5) * a_len * 0.7, arrow_y - math.sin(angle + 2.5) * a_len * 0.7)
        p3 = (arrow_x + math.cos(angle - 2.5) * a_len * 0.7, arrow_y - math.sin(angle - 2.5) * a_len * 0.7)
        pygame.draw.polygon(screen, main_color, [p1, p2, p3])
        pygame.draw.polygon(screen, (20, 20, 20), [p1, p2, p3], 1)

        # Distance tag on edge pointer
        d_str = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.1f}km"
        tag = "PICKUP" if is_pickup else "DROPOFF"
        d_surf = font.render(f"{tag} {d_str}", True, (255, 255, 255))
        d_rect = d_surf.get_rect(center=(arrow_x, arrow_y + 18 if arrow_y < screen_h - 40 else arrow_y - 18))
        d_bg = pygame.Surface((d_rect.width + 6, d_rect.height + 4), pygame.SRCALPHA)
        d_bg.fill((15, 15, 15, 210))
        screen.blit(d_bg, (d_rect.x - 3, d_rect.y - 2))
        screen.blit(d_surf, d_rect)


def draw_compass(screen, car: Car, cx: int, cy: int, r: int, font, target_pos: Optional[tuple[float, float]] = None) -> None:
    """Draw circular north-up compass with heading needle, bearing degrees, and taxi nav arrow."""
    import pygame

    pygame.draw.circle(screen, (40, 40, 40), (cx, cy), r)
    pygame.draw.circle(screen, (200, 200, 200), (cx, cy), r, 2)

    n_t = font.render("N", True, (240, 240, 240))
    n_rect = n_t.get_rect(center=(cx, cy - r + 10))
    screen.blit(n_t, n_rect)

    # If taxi destination exists, draw green/gold guidance pointer
    if target_pos:
        tx, ty = target_pos
        dx = tx - car.x
        dy = ty - car.y
        t_ang = math.atan2(dy, dx)
        # Draw destination indicator arrow on compass ring
        t_nx = cx + math.cos(t_ang) * (r - 4)
        t_ny = cy - math.sin(t_ang) * (r - 4)
        t_ah = 8
        t_p1 = (t_nx + math.cos(t_ang + 2.5) * t_ah, t_ny - math.sin(t_ang + 2.5) * t_ah)
        t_p2 = (t_nx + math.cos(t_ang - 2.5) * t_ah, t_ny - math.sin(t_ang - 2.5) * t_ah)
        pygame.draw.polygon(screen, (255, 215, 0), [(t_nx, t_ny), t_p1, t_p2])

    ang = car.heading
    nx = cx + math.cos(ang) * (r - 8)
    ny = cy - math.sin(ang) * (r - 8)
    pygame.draw.line(screen, (220, 40, 40), (cx, cy), (nx, ny), 3)

    ah = 6
    ph1 = (nx + math.cos(ang + 2.4) * ah, ny - math.sin(ang + 2.4) * ah)
    ph2 = (nx + math.cos(ang - 2.4) * ah, ny - math.sin(ang - 2.4) * ah)
    pygame.draw.polygon(screen, (220, 40, 40), [(nx, ny), ph1, ph2])

    deg = (90.0 - math.degrees(ang)) % 360.0
    b_t = font.render(f"{int(deg):03d}\u00B0", True, (240, 240, 240))
    b_rect = b_t.get_rect(center=(cx, cy + r - 12))
    screen.blit(b_t, b_rect)


def draw_loading_screen(
    screen,
    font,
    progress: float,
    message: str = "Loading scenery...",
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw a standalone loading screen with a progress meter bar and message."""
    import pygame

    # Background
    screen.fill((20, 25, 30))

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 40, bold=True)
    except Exception:
        pass
    title_surf = title_font.render("THE ROAD RAGE TRIP", True, (240, 240, 240))
    title_rect = title_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 70))
    screen.blit(title_surf, title_rect)

    # Subtitle
    sub_surf = font.render("Loading OpenStreetMap roads & scenery...", True, (160, 175, 190))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, screen_h // 2 - 35))
    screen.blit(sub_surf, sub_rect)

    # Progress bar dimensions
    bar_w = 440
    bar_h = 24
    bar_x = (screen_w - bar_w) // 2
    bar_y = screen_h // 2 + 5

    # Outer frame and background
    pygame.draw.rect(screen, (35, 42, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=4)
    pygame.draw.rect(screen, (100, 115, 130), (bar_x, bar_y, bar_w, bar_h), width=2, border_radius=4)

    # Fill
    clamped_prog = max(0.0, min(1.0, progress))
    fill_w = int((bar_w - 4) * clamped_prog)
    if fill_w > 0:
        pygame.draw.rect(screen, (40, 180, 100), (bar_x + 2, bar_y + 2, fill_w, bar_h - 4), border_radius=2)

    # Percentage and message
    pct_str = f"{int(clamped_prog * 100)}%"
    msg_surf = font.render(f"{message} ({pct_str})", True, (220, 230, 240))
    msg_rect = msg_surf.get_rect(center=(screen_w // 2, bar_y + bar_h + 22))
    screen.blit(msg_surf, msg_rect)


def draw_hud(
    screen,
    font,
    car: Car,
    on_road: bool,
    ways_count: int,
    px_per_m: float,
    transformer_to_ll,
    is_auto_fetching: bool = False,
    show_labels: bool = True,
    auto_fetch_progress: float = 0.0,
    taxi_mgr: Optional[TaxiManager] = None,
) -> None:
    """Draw speed, trip, odometer, on-road status, lat/lon, taxi mission bar, notifications."""
    import pygame

    lat, lon = meters_to_latlon(car.x, car.y, transformer=transformer_to_ll)
    lat_s = f"{lat:.5f}" if lat is not None else "N/A"
    lon_s = f"{lon:.5f}" if lon is not None else "N/A"

    trip_s = f"{car.trip_m:.0f} m" if car.trip_m < 1000 else f"{car.trip_m / 1000.0:.2f} km"
    odo_s = f"{car.odometer_m / 1000.0:.2f} km" if car.odometer_m >= 1000 else f"{car.odometer_m:.0f} m"

    labels_status = "ON" if show_labels else "OFF"
    hud = (
        f"Speed: {car.speed * 3.6:.0f} km/h | Trip: {trip_s} | Odo: {odo_s} | "
        f"On road: {'YES' if on_road else 'NO'} | Ways: {ways_count} | Zoom: {px_per_m:.2f} px/m | Lat: {lat_s} Lon: {lon_s}"
    )
    text = font.render(hud, True, (240, 240, 240))
    screen.blit(text, (10, 10))

    hint = f"Controls: W/S/A/D = drive | +/- = zoom | R = respawn | T = reset trip | L = labels ({labels_status})"
    hint_t = font.render(hint, True, (220, 220, 220))
    screen.blit(hint_t, (10, 34))

    # Taxi mission banner / status bar
    if taxi_mgr:
        taxi_y = 58
        target = taxi_mgr.get_current_target()
        dist_m = math.hypot(car.x - target.x, car.y - target.y) if target else 0.0
        dist_s = f"{dist_m:.0f}m" if dist_m < 1000 else f"{dist_m / 1000.0:.2f}km"

        p = taxi_mgr.current_passenger
        if taxi_mgr.state == TaxiState.WAITING_FOR_PICKUP:
            role_text = f"🚖 FARE: Pickup {p.name if p else 'Client'} at: {target.address if target else '...'} ({dist_s})"
            role_color = (255, 215, 60)
        else:
            cur_speed_kmh = (dist_m / max(1.0, taxi_mgr.elapsed_time)) * 3.6 if taxi_mgr.elapsed_time > 0 else 0.0
            role_text = (
                f"🚖 FARE: Take {p.name if p else 'Client'} to: {target.address if target else '...'} "
                f"({dist_s} left, Time: {taxi_mgr.elapsed_time:.1f}s)"
            )
            role_color = (100, 240, 140)

        # Draw taxi score and stats on top right
        score_text = f"SCORE: {taxi_mgr.total_score} pts | Fares: {taxi_mgr.completed_fares}"
        score_surf = font.render(score_text, True, (255, 230, 110))
        score_rect = score_surf.get_rect(topright=(SCREEN_W - 140, 10))
        bg_s = pygame.Surface((score_rect.width + 12, score_rect.height + 6), pygame.SRCALPHA)
        bg_s.fill((20, 20, 20, 200))
        screen.blit(bg_s, (score_rect.x - 6, score_rect.y - 3))
        pygame.draw.rect(screen, (220, 180, 50), (score_rect.x - 6, score_rect.y - 3, score_rect.width + 12, score_rect.height + 6), 1, border_radius=3)
        screen.blit(score_surf, score_rect)

        # Mission header bar
        mission_surf = font.render(role_text, True, role_color)
        m_rect = mission_surf.get_rect(topleft=(10, taxi_y))
        m_bg = pygame.Surface((m_rect.width + 12, m_rect.height + 6), pygame.SRCALPHA)
        m_bg.fill((25, 30, 35, 220))
        screen.blit(m_bg, (m_rect.x - 6, m_rect.y - 3))
        pygame.draw.rect(screen, role_color, (m_rect.x - 6, m_rect.y - 3, m_rect.width + 12, m_rect.height + 6), 1, border_radius=3)
        screen.blit(mission_surf, m_rect)

        # In-game notification banner (e.g. Fare completed, new pickup)
        if taxi_mgr.notification_timer > 0.0 and taxi_mgr.notification_msg:
            notif_surf = font.render(taxi_mgr.notification_msg, True, (255, 255, 255))
            notif_rect = notif_surf.get_rect(center=(SCREEN_W // 2, SCREEN_H - 45))
            n_bg = pygame.Surface((notif_rect.width + 24, notif_rect.height + 12), pygame.SRCALPHA)
            n_bg.fill((20, 30, 40, 235))
            screen.blit(n_bg, (notif_rect.x - 12, notif_rect.y - 6))
            pygame.draw.rect(screen, (255, 200, 50), (notif_rect.x - 12, notif_rect.y - 6, notif_rect.width + 24, notif_rect.height + 12), 2, border_radius=5)
            screen.blit(notif_surf, notif_rect)

    # Auto-fetch scenery loading progress meter
    if is_auto_fetching:
        prog = max(0.0, min(1.0, auto_fetch_progress if auto_fetch_progress > 0.0 else 0.65))
        bar_w = 160
        bar_h = 14
        bar_x = 10
        bar_y = 86 if taxi_mgr else 58

        # Background and border
        pygame.draw.rect(screen, (30, 35, 40), (bar_x, bar_y, bar_w, bar_h), border_radius=3)
        pygame.draw.rect(screen, (140, 150, 160), (bar_x, bar_y, bar_w, bar_h), width=1, border_radius=3)

        # Progress fill
        fill_w = int((bar_w - 2) * prog)
        if fill_w > 0:
            pygame.draw.rect(screen, (255, 190, 40), (bar_x + 1, bar_y + 1, fill_w, bar_h - 2), border_radius=2)

        load_t = font.render(f"Loading scenery... {int(prog * 100)}%", True, (255, 215, 60))
        screen.blit(load_t, (bar_x + bar_w + 10, bar_y - 2))

