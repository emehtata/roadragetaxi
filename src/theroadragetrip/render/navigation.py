from .common import (
    SCREEN_W,
    SCREEN_H,
    PX_PER_M,
    world_to_screen,
)
import math
from typing import List, Optional, Tuple


from ..physics import Car
from ..taxi import TaxiManager, TaxiState
from ..localization import tr


def draw_taxi_target(
    screen,
    taxi_mgr: TaxiManager,
    camx: float,
    camy: float,
    font,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw pulsing waypoint circle, pin icon, and on-screen navigation arrow for active pickup/dropoff."""
    import pygame

    target = taxi_mgr.get_current_target()
    if not target:
        return

    is_pickup = taxi_mgr.state in (TaxiState.WAITING_FOR_PICKUP, TaxiState.CLIENT_WALKING_TO_CAR)
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
        tag_text = tr(language, "pickup") if is_pickup else tr(language, "to")
        lbl_surf = font.render(f"[{tag_text}] {target.address}", True, (255, 255, 255))
        rect = lbl_surf.get_rect(center=(sx, sy - rad_px - 14))
        bg_rect = rect.inflate(8, 4)
        bg = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 220))
        screen.blit(bg, bg_rect.topleft)
        pygame.draw.rect(screen, main_color, bg_rect, width=1, border_radius=3)
        screen.blit(lbl_surf, rect)


        # Draw client pedestrian waiting or walking into the taxi
        p = taxi_mgr.current_passenger
        if is_pickup and p and not p.boarded:
            ped_sx, ped_sy = world_to_screen(p.ped_x, p.ped_y, camx, camy, px_per_m, screen_w, screen_h)
            ped_r = max(4.0, 0.5 * px_per_m)
            # Outline
            pygame.draw.circle(screen, (20, 20, 20), (int(ped_sx), int(ped_sy)), int(ped_r + 2))
            # Client body in distinct passenger color
            pygame.draw.circle(screen, p.ped_color, (int(ped_sx), int(ped_sy)), int(ped_r))
            # Heading notch
            hx = ped_sx + math.cos(p.ped_heading) * (ped_r * 0.9)
            hy = ped_sy + math.sin(p.ped_heading) * (ped_r * 0.9)
            pygame.draw.circle(screen, (255, 255, 255), (int(hx), int(hy)), max(1, int(ped_r * 0.45)))

            # Passenger name tag over client
            walking_label = "KYYTIIN" if language == "fi" else "TO TAXI"
            p_lbl = font.render(
                f"[{walking_label}] {p.name}" if p.is_walking_to_car else f"[P] {p.name}",
                True,
                (255, 230, 80),
            )
            p_rect = p_lbl.get_rect(center=(int(ped_sx), int(ped_sy - ped_r - 12)))
            p_bg = pygame.Surface((p_rect.width + 6, p_rect.height + 4), pygame.SRCALPHA)
            p_bg.fill((20, 20, 20, 200))
            screen.blit(p_bg, (p_rect.left - 3, p_rect.top - 2))
            screen.blit(p_lbl, p_rect)
    else:
        # Off-screen direction indicator arrow pointing towards target
        dx = target.x - camx
        dy = target.y - camy
        angle = math.atan2(dy, dx)
        dist_m = math.hypot(dx, dy)

        # Screen margin clamp for arrow
        edge_margin = 130
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
        tag = tr(language, "pickup_short") if is_pickup else tr(language, "dropoff_short")
        d_surf = font.render(f"{tag} {d_str}", True, (255, 255, 255))
        d_rect = d_surf.get_rect(center=(arrow_x, arrow_y + 18 if arrow_y < screen_h - 40 else arrow_y - 18))
        d_bg = pygame.Surface((d_rect.width + 6, d_rect.height + 4), pygame.SRCALPHA)
        d_bg.fill((15, 15, 15, 210))
        screen.blit(d_bg, (d_rect.x - 3, d_rect.y - 2))
        screen.blit(d_surf, d_rect)


def draw_navigation_route(
    screen,
    route: Optional[List[Tuple[float, float]]],
    camx: float,
    camy: float,
    px_per_m: float = PX_PER_M,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw the active taxi route above roads and below gameplay markers."""
    import pygame

    if not route or len(route) < 2:
        return
    points = [
        world_to_screen(x, y, camx, camy, px_per_m, screen_w, screen_h)
        for x, y in route
    ]
    pygame.draw.lines(screen, (60, 45, 5), False, points, max(5, int(px_per_m * 0.8)))
    pygame.draw.lines(screen, (255, 215, 35), False, points, max(2, int(px_per_m * 0.45)))


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
