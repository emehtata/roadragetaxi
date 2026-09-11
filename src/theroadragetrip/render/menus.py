from .common import (
    SCREEN_W,
    SCREEN_H,
    _draw_version,
)
import os
from typing import List, Optional


from ..localization import tr


_loading_image = None
_loading_image_path = os.path.join(os.path.dirname(__file__), "..", "img", "theroadragetrip_1672_941.png")


def draw_loading_screen(
    screen,
    font,
    progress: float,
    message: str = "Loading scenery...",
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    show_details: bool = True,
    language: str = "fi",
) -> None:
    """Draw a standalone loading screen with a progress meter bar and message."""
    import pygame

    global _loading_image

    if _loading_image is None and os.path.exists(_loading_image_path):
        try:
            _loading_image = pygame.image.load(_loading_image_path).convert()
        except pygame.error:
            _loading_image = False

    if _loading_image:
        image_w, image_h = _loading_image.get_size()
        scale = max(screen_w / image_w, screen_h / image_h)
        scaled_size = (round(image_w * scale), round(image_h * scale))
        background = pygame.transform.smoothscale(_loading_image, scaled_size)
        image_x = (screen_w - scaled_size[0]) // 2
        image_y = (screen_h - scaled_size[1]) // 2
        screen.blit(background, (image_x, image_y))
        overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 105))
        screen.blit(overlay, (0, 0))
    else:
        screen.fill((20, 25, 30))

    if not show_details:
        return

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
    sub_surf = font.render(tr(language, "loading_osm"), True, (160, 175, 190))
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

    pct_str = f"{int(clamped_prog * 100)}%"
    msg_surf = font.render(pct_str, True, (220, 230, 240))
    msg_rect = msg_surf.get_rect(center=(screen_w // 2, bar_y + bar_h + 22))
    screen.blit(msg_surf, msg_rect)

    # Live status line - what's actually happening right now (which
    # endpoint/file is being read, cache hit, parsing, ...), not just a
    # percentage. `message` carries this from the fetch's own
    # progress_callback (see osm/overpass.py, osm/pbf_source.py) - it used
    # to be computed and passed all the way here but never actually drawn.
    if message:
        detail_font = font
        try:
            detail_font = pygame.font.SysFont(None, 18)
        except Exception:
            pass
        detail_surf = detail_font.render(message, True, (150, 165, 180))
        detail_rect = detail_surf.get_rect(center=(screen_w // 2, bar_y + bar_h + 44))
        screen.blit(detail_surf, detail_rect)


def draw_game_start_overlay(
    screen,
    font,
    city: str,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
) -> None:
    """Draw the city sign and prompt shown before gameplay starts."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 105))
    screen.blit(overlay, (0, 0))

    sign_font = pygame.font.SysFont(None, max(34, min(68, screen_w // 12)), bold=True)
    prompt_font = pygame.font.SysFont(None, max(22, min(34, screen_w // 24)))
    city_surface = sign_font.render(city.upper(), True, (255, 255, 255))
    prompt_surface = prompt_font.render("Paina mitä tahansa aloittaaksesi", True, (255, 255, 255))
    sign_width = max(city_surface.get_width(), prompt_surface.get_width()) + 80
    sign_height = city_surface.get_height() + prompt_surface.get_height() + 54
    sign = pygame.Rect(0, 0, sign_width, sign_height)
    sign.center = (screen_w // 2, screen_h // 2)
    pygame.draw.rect(screen, (28, 84, 155), sign, border_radius=8)
    pygame.draw.rect(screen, (220, 235, 255), sign, width=3, border_radius=8)
    screen.blit(city_surface, city_surface.get_rect(center=(sign.centerx, sign.top + city_surface.get_height() // 2 + 14)))
    screen.blit(
        prompt_surface,
        prompt_surface.get_rect(center=(sign.centerx, sign.bottom - prompt_surface.get_height() // 2 - 14)),
    )


def draw_game_start_hint(
    screen,
    font,
    screen_w: int = SCREEN_W,
) -> None:
    """Draw the first gameplay control hint."""
    import pygame

    hint_font = pygame.font.SysFont(None, max(20, min(30, screen_w // 28)), bold=True)
    hint = hint_font.render("Painamalla F pääset sisään taksiisi", True, (255, 255, 255))
    padding_x = 18
    padding_y = 10
    box = hint.get_rect(center=(screen_w // 2, 76)).inflate(padding_x * 2, padding_y * 2)
    pygame.draw.rect(screen, (16, 35, 55), box, border_radius=5)
    pygame.draw.rect(screen, (100, 190, 240), box, width=2, border_radius=5)
    screen.blit(hint, hint.get_rect(center=box.center))


def draw_city_selection_menu(
    screen,
    font,
    cities: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
    force_refresh: bool = False,
) -> None:
    """Draw city selection menu with 10 largest cities in Finland."""
    import pygame

    draw_loading_screen(screen, font, 1.0, tr(language, "ready"), screen_w, screen_h, show_details=False, language=language)
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((8, 14, 22, 135))
    screen.blit(overlay, (0, 0))

    # Header / Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 38, bold=True)
    except Exception:
        pass

    t_surf = title_font.render("THE ROAD RAGE TRIP", True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, 45))
    screen.blit(t_surf, t_rect)

    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 22)
    except Exception:
        pass

    sub_surf = sub_font.render(tr(language, "select_city"), True, (150, 180, 210))
    sub_rect = sub_surf.get_rect(center=(screen_w // 2, 80))
    screen.blit(sub_surf, sub_rect)

    # 2-column city grid
    cols = 2
    rows = (len(cities) + cols - 1) // cols
    item_w = 320
    item_h = 42
    gap_x = 24
    gap_y = 10
    total_w = cols * item_w + (cols - 1) * gap_x
    start_x = (screen_w - total_w) // 2
    start_y = 115

    for idx, city in enumerate(cities):
        col = idx // rows
        row = idx % rows
        ix = start_x + col * (item_w + gap_x)
        iy = start_y + row * (item_h + gap_y)

        is_sel = idx == selected_idx
        bg_color = (45, 80, 130) if is_sel else (28, 36, 48)
        border_color = (100, 200, 255) if is_sel else (60, 75, 95)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        num_prefix = f"{('1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ'[idx])}: "
        city_label = f"{num_prefix}{city}"
        if is_sel:
            city_label = f"> {city_label}"

        c_surf = font.render(city_label, True, text_color)
        c_rect = c_surf.get_rect(midleft=(ix + 16, iy + item_h // 2))
        screen.blit(c_surf, c_rect)

    checkbox_rect = pygame.Rect(screen_w // 2 - 150, start_y + rows * (item_h + gap_y) + 12, 22, 22)
    pygame.draw.rect(screen, (28, 36, 48), checkbox_rect, border_radius=3)
    pygame.draw.rect(screen, (100, 200, 255) if force_refresh else (100, 115, 130), checkbox_rect, width=2, border_radius=3)
    if force_refresh:
        pygame.draw.line(screen, (120, 235, 150), checkbox_rect.topleft, checkbox_rect.center, 3)
        pygame.draw.line(screen, (120, 235, 150), checkbox_rect.center, checkbox_rect.bottomright, 3)
    refresh_surf = sub_font.render(tr(language, "refresh_map"), True, (220, 230, 235))
    screen.blit(refresh_surf, refresh_surf.get_rect(midleft=(checkbox_rect.right + 10, checkbox_rect.centery)))

    edit_rect = pygame.Rect(screen_w // 2 - 150, checkbox_rect.bottom + 16, 300, 36)
    pygame.draw.rect(screen, (45, 80, 130), edit_rect, border_radius=5)
    pygame.draw.rect(screen, (100, 200, 255), edit_rect, width=1, border_radius=5)
    edit_surf = sub_font.render(tr(language, "edit_city_list"), True, (255, 255, 255))
    screen.blit(edit_surf, edit_surf.get_rect(center=edit_rect.center))

    # Navigation hint
    hint_surf = sub_font.render(
        tr(language, "city_hint"),
        True,
        (130, 150, 170),
    )
    hint_rect = hint_surf.get_rect(center=(screen_w // 2, screen_h - 35))
    screen.blit(hint_surf, hint_rect)
    _draw_version(screen, sub_font, screen_w, screen_h)


def draw_mode_selection_menu(screen, font, selected_idx: int, screen_w: int = SCREEN_W, screen_h: int = SCREEN_H, language: str = "fi") -> None:
    """Draw the initial game-mode selection menu."""
    import pygame

    draw_loading_screen(screen, font, 1.0, tr(language, "ready"), screen_w, screen_h, show_details=False, language=language)
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((8, 14, 22, 145))
    screen.blit(overlay, (0, 0))
    title = font.render(tr(language, "select_mode"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 170)))
    options = [
        tr(language, "career"),
        tr(language, "gig_driver"),
        tr(language, "reset_career"),
        tr(language, "clear_cache"),
    ]
    for index, option in enumerate(options):
        color = (255, 215, 95) if index == selected_idx else (210, 220, 230)
        label = font.render(f"{index + 1}. {option}", True, color)
        screen.blit(label, label.get_rect(center=(screen_w // 2, 270 + index * 60)))
    hint = pygame.font.SysFont(None, 18).render(tr(language, "language_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 80)))
    _draw_version(screen, font, screen_w, screen_h)


def draw_city_summary(
    screen, font, city: str, score: int, fares: int, next_city: Optional[str] = None,
    career_total_score: Optional[int] = None,
    screen_w: int = SCREEN_W, screen_h: int = SCREEN_H, language: str = "fi",
) -> None:
    """Draw the completion summary shown before career mode continues."""
    import pygame

    screen.fill((18, 24, 32))
    title = font.render(tr(language, "city_summary"), True, (255, 215, 95))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 180)))
    lines = [
        city,
        tr(language, "city_summary_score", score=score),
        tr(language, "city_summary_fares", fares=fares),
    ]
    if next_city:
        lines.append(tr(language, "next_city", city=next_city))
    else:
        lines.append(tr(language, "career_complete"))
        if career_total_score is not None:
            lines.append(tr(language, "career_total_score", score=career_total_score))
    for index, line in enumerate(lines):
        color = (245, 245, 245) if index == 0 else (205, 215, 225)
        text = font.render(line, True, color)
        screen.blit(text, text.get_rect(center=(screen_w // 2, 260 + index * 42)))
    hint = pygame.font.SysFont(None, 20).render(tr(language, "continue_enter"), True, (255, 215, 95))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 100)))


def draw_tutorial_screen(
    screen,
    font,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw the game's tutorial, objective, and complete control list."""
    import pygame

    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((5, 10, 16, 220))
    screen.blit(overlay, (0, 0))

    panel = pygame.Rect(90, 45, screen_w - 180, screen_h - 90)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)

    title_font = pygame.font.SysFont(None, 38, bold=True)
    section_font = pygame.font.SysFont(None, 25, bold=True)
    title = title_font.render(tr(language, "tutorial"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 38)))

    sections = [
        (tr(language, "story"), [
            "Olet kaiken kokenut taksikuski, joka ajaa keikkaa Suomen eri kaupungeissa." if language == "fi" else "You are a veteran taxi driver working rides across Finnish cities.",
            "Joka paikkaa yhdistävät samat riesat: idiootit kanssakuskit, ääliöt pyöräilijät" if language == "fi" else "Everywhere has the same problems: foolish drivers, awful cyclists",
            "ja eteen pyrkivät jalankulkijat. Vuosien ajo on kehittänyt sinulle supervoiman:" if language == "fi" else "and pedestrians stepping in front of you. Years on the road gave you a superpower:",
            "rattiraivo tyhjentää tien häiriöistä. Rattiraivo-mittari kasvaa rajoitusten mukaan ajaessa" if language == "fi" else "Road Rage clears obstacles. Road Rage grows when you follow limits",
            "ja pienenee, kun käytät rattiraivoa tehdäksesi tietä." if language == "fi" else "and drains when you use Road Rage to clear the way.",
        ]),
        (tr(language, "idea"), [
            "Aja asiakkaan luo, ota hänet kyytiin ja vie perille." if language == "fi" else "Drive to clients, pick them up, and take them to their destination.",
            "Nouda asiakkaat kaduilta, taksiasemilta tai nimetyiltä rakennuksilta." if language == "fi" else "Pick up clients from streets, taxi stops, or named buildings.",
            "Pysy tiellä, vältä kolareita ja kerää pisteitä nopeista onnistuneista kyydeistä." if language == "fi" else "Stay on the road, avoid crashes, and score points for successful rides.",
            "Puhelin näyttää kolme kyytiä: valitse yksi näppäimillä 1-3 tai hylkää tarjous X:llä." if language == "fi" else "The phone shows three rides: select one with 1-3 or reject an offer with X.",
            "Taksitolpan asiakas näyttää KYYTIIN-tekstin, kävelee autolle ja voi päätyä kilpailevalle NPC-taksille." if language == "fi" else "A taxi-stand customer shows TO TAXI, walks to the car, or may choose a rival NPC taxi.",
            "Aja rajoituksen mukaan: se kasvattaa rattiraivoa. Hidas lähestyminen punaista valoa kasvattaa sitä myös." if language == "fi" else "Follow the speed limit to build Road Rage. Approaching a red light slowly also builds it.",
            "Space kuluttaa 25 % mittarista ja siirtää edessä olevat ajoneuvot sivuun 50 metrin säteellä." if language == "fi" else "Space spends 25% of the meter and moves vehicles ahead aside within 50 meters.",
            "Se pysäyttää aktiivisen poliisin takaa-ajon kokonaan; poliisi kääntyy pois kolmeksi sekunniksi." if language == "fi" else "It ends an active police pursuit; the police turn away for three seconds.",
            "Kolarit nollaavat mittarin ja pyöräilijään törmääminen puolittaa sen." if language == "fi" else "Crashes empty the meter and hitting a cyclist halves it.",
            "Zoomaus vähentää kaukana olevia NPC-hahmoja suorituskyvyn parantamiseksi." if language == "fi" else "Zooming in reduces distant NPC characters to improve performance.",
        ]),
    ]
    y = panel.y + 78
    for heading, lines in sections:
        heading_surface = section_font.render(heading, True, (255, 215, 95))
        screen.blit(heading_surface, (panel.x + 28, y))
        y += 30
        for line in lines:
            line_surface = font.render(line, True, (220, 228, 235))
            screen.blit(line_surface, (panel.x + 42, y))
            y += 21
        y += 10

    control_font = pygame.font.SysFont("monospace", 18)
    controls = [
        ("W / Up", tr(language, "drive")),
        ("S / Down", tr(language, "brake")),
        ("A / Left", tr(language, "left")),
        ("D / Right", tr(language, "right")),
        ("P", tr(language, "phone")),
        ("1 - 3", tr(language, "select_ride")),
        ("Space", tr(language, "rage")),
        ("R", tr(language, "respawn")),
        ("X", tr(language, "cancel_ride")),
        ("T", tr(language, "reset_trip")),
        ("L", tr(language, "labels")),
        ("K", tr(language, "lane_assist")),
        ("V", tr(language, "speed_limiter")),
        ("B", tr(language, "red_assist")),
        ("N", "Navigointi" if language == "fi" else "Toggle navigation route"),
        ("+ / -", tr(language, "zoom")),
        ("Esc", tr(language, "pause")),
        ("F1", tr(language, "help_short")),
        ("F3", "Näytä/piilota debug-HUD" if language == "fi" else "Toggle diagnostic HUD"),
        ("F12", tr(language, "screenshot")),
        ("F", tr(language, "exit_car")),
    ]
    heading_surface = section_font.render(tr(language, "controls"), True, (255, 215, 95))
    screen.blit(heading_surface, (panel.x + 28, y))
    y += 30
    column_count = 3
    column_width = panel.width // column_count
    rows_per_column = (len(controls) + column_count - 1) // column_count
    for row in range(rows_per_column):
        for column in range(column_count):
            index = row + column * rows_per_column
            if index >= len(controls):
                continue
            key, action = controls[index]
            column_x = panel.x + 28 + column * column_width
            key_surface = control_font.render(key, True, (255, 215, 95))
            action_surface = pygame.font.SysFont(None, 18).render(action, True, (220, 228, 235))
            screen.blit(key_surface, (column_x, y))
            screen.blit(action_surface, (column_x + 82, y))
        y += 18

    hint = font.render(tr(language, "help_close"), True, (160, 190, 215))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 25)))


def draw_pause_menu(
    screen,
    font,
    options: List[str],
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw semi-transparent pause menu overlay with selectable options."""
    import pygame

    # Semi-transparent dark overlay
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((10, 15, 20, 190))
    screen.blit(overlay, (0, 0))

    # Menu panel
    panel_w = min(420, screen_w - 40)
    panel_h = min(screen_h - 40, max(280, 110 + len(options) * 56))
    panel_x = (screen_w - panel_w) // 2
    panel_y = (screen_h - panel_h) // 2

    panel_surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel_surf.fill((22, 28, 38, 230))
    screen.blit(panel_surf, (panel_x, panel_y))
    pygame.draw.rect(screen, (70, 120, 180), (panel_x, panel_y, panel_w, panel_h), width=2, border_radius=8)

    # Title
    title_font = font
    try:
        title_font = pygame.font.SysFont(None, 36, bold=True)
    except Exception:
        pass
    t_surf = title_font.render(tr(language, "paused"), True, (245, 245, 245))
    t_rect = t_surf.get_rect(center=(screen_w // 2, panel_y + 40))
    screen.blit(t_surf, t_rect)

    # Options buttons
    item_w = 340
    item_h = 44
    start_y = panel_y + 80
    gap_y = 12

    for idx, opt in enumerate(options):
        iy = start_y + idx * (item_h + gap_y)
        ix = panel_x + (panel_w - item_w) // 2

        is_sel = idx == selected_idx
        bg_color = (45, 85, 140) if is_sel else (32, 40, 52)
        border_color = (100, 200, 255) if is_sel else (65, 80, 100)
        text_color = (255, 255, 255) if is_sel else (200, 210, 220)

        pygame.draw.rect(screen, bg_color, (ix, iy, item_w, item_h), border_radius=6)
        pygame.draw.rect(screen, border_color, (ix, iy, item_w, item_h), width=2 if is_sel else 1, border_radius=6)

        prefix = "> " if is_sel else "   "
        o_surf = font.render(f"{prefix}{opt}", True, text_color)
        o_rect = o_surf.get_rect(midleft=(ix + 20, iy + item_h // 2))
        screen.blit(o_surf, o_rect)

    # Hint
    sub_font = font
    try:
        sub_font = pygame.font.SysFont(None, 18)
    except Exception:
        pass
    h_surf = sub_font.render(tr(language, "select_choose_resume"), True, (140, 160, 180))
    h_rect = h_surf.get_rect(center=(screen_w // 2, panel_y + panel_h - 20))
    screen.blit(h_surf, h_rect)
    _draw_version(screen, font, screen_w, screen_h)


def draw_settings_menu(
    screen,
    font,
    language: str,
    master_volume: float,
    music_volume: float,
    effects_volume: float,
    comments_enabled: bool,
    subtitles_enabled: bool,
    overpass_endpoints: str,
    selected_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    physics_mode: str = "arcade",
) -> None:
    """Draw language, audio, Overpass endpoint, and driving-physics settings."""
    import pygame

    screen.fill((18, 24, 32))
    panel = pygame.Rect(100, 70, screen_w - 200, screen_h - 140)
    pygame.draw.rect(screen, (22, 30, 40), panel, border_radius=8)
    pygame.draw.rect(screen, (100, 170, 220), panel, width=2, border_radius=8)
    title_font = pygame.font.SysFont(None, 36, bold=True)
    title = title_font.render(tr(language, "settings"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, panel.y + 42)))

    rows = [
        (tr(language, "language"), "Suomi" if language == "fi" else "English", None),
        (tr(language, "master_volume"), f"{master_volume * 100:.0f}%", master_volume),
        (tr(language, "music_volume"), f"{music_volume * 100:.0f}%", music_volume),
        (tr(language, "effects_volume"), f"{effects_volume * 100:.0f}%", effects_volume),
        (tr(language, "comment_audio"), tr(language, "on" if comments_enabled else "off"), None),
        (tr(language, "subtitles"), tr(language, "on" if subtitles_enabled else "off"), None),
        (tr(language, "overpass_endpoints"), overpass_endpoints[-55:] if len(overpass_endpoints) > 55 else overpass_endpoints, None),
        (tr(language, "physics_mode"), tr(language, physics_mode), None),
    ]
    for idx, (label, value, volume) in enumerate(rows):
        y = panel.y + 100 + idx * 58
        selected = idx == selected_idx
        color = (255, 215, 95) if selected else (220, 228, 235)
        label_surface = font.render(label, True, color)
        screen.blit(label_surface, (panel.x + 38, y))
        if volume is None:
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 400, y))
        else:
            bar = pygame.Rect(panel.right - 240, y + 5, 150, 16)
            pygame.draw.rect(screen, (45, 55, 65), bar, border_radius=3)
            pygame.draw.rect(screen, (55, 180, 110), (bar.x, bar.y, int(bar.width * volume), bar.height), border_radius=3)
            value_surface = font.render(value, True, color)
            screen.blit(value_surface, (panel.right - 75, y))

    hint = pygame.font.SysFont(None, 18).render(tr(language, "settings_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, panel.bottom - 28)))


def draw_city_editor(
    screen,
    font,
    cities: List[str],
    selected_idx: int,
    query: str,
    suggestions: List[str],
    suggestion_idx: int,
    screen_w: int = SCREEN_W,
    screen_h: int = SCREEN_H,
    language: str = "fi",
) -> None:
    """Draw the searchable city replacement editor."""
    import pygame

    screen.fill((18, 24, 32))
    title = pygame.font.SysFont(None, 32, bold=True).render(tr(language, "city_editor"), True, (245, 245, 245))
    screen.blit(title, title.get_rect(center=(screen_w // 2, 38)))
    rows = (len(cities) + 1) // 2
    item_w, item_h, gap_x, gap_y = 300, 38, 20, 8
    start_x = (screen_w - (2 * item_w + gap_x)) // 2
    start_y = 72
    for idx, city in enumerate(cities):
        col = idx // rows
        row = idx % rows
        rect = pygame.Rect(start_x + col * (item_w + gap_x), start_y + row * (item_h + gap_y), item_w, item_h)
        selected = idx == selected_idx
        pygame.draw.rect(screen, (45, 80, 130) if selected else (28, 36, 48), rect, border_radius=5)
        pygame.draw.rect(screen, (100, 200, 255) if selected else (60, 75, 95), rect, width=2 if selected else 1, border_radius=5)
        screen.blit(font.render(f"{idx + 1}. {city}", True, (255, 255, 255)), (rect.x + 12, rect.y + 8))

    input_rect = pygame.Rect(screen_w // 2 - 250, start_y + rows * (item_h + gap_y) + 20, 500, 42)
    pygame.draw.rect(screen, (245, 245, 245), input_rect, border_radius=4)
    pygame.draw.rect(screen, (255, 215, 95), input_rect, width=2, border_radius=4)
    screen.blit(font.render(query or tr(language, "city_editor_search"), True, (30, 35, 42) if query else (120, 130, 140)), (input_rect.x + 12, input_rect.y + 9))
    for idx, suggestion in enumerate(suggestions):
        rect = pygame.Rect(input_rect.x, input_rect.bottom + 8 + idx * 34, input_rect.width, 30)
        pygame.draw.rect(screen, (55, 95, 130) if idx == suggestion_idx else (32, 43, 55), rect, border_radius=3)
        screen.blit(font.render(suggestion, True, (255, 255, 255)), (rect.x + 12, rect.y + 5))
    hint = pygame.font.SysFont(None, 18).render(tr(language, "city_editor_hint"), True, (150, 175, 195))
    screen.blit(hint, hint.get_rect(center=(screen_w // 2, screen_h - 25)))


draw_help_screen = draw_tutorial_screen
