import logging
import sys
from datetime import date, datetime

import pygame

from ..config import (
    city_suggestions,
    cities_from_config,
    load_city_catalog,
    replace_city_in_config,
    save_config,
)
from ..localization import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, normalize_language, tr
from .menu_input import (
    _city_editor_item_at,
    _city_editor_suggestion_at,
    _menu_item_at_y,
)
from ..render import (
    SCREEN_H,
    SCREEN_W,
    draw_city_editor,
)


logger = logging.getLogger(__name__)


def _one_calendar_year_ago(day: date) -> date:
    """Return the same date last year, clamping leap day to February 28."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _clamp_start_datetime(value: datetime, today: date) -> datetime:
    earliest = _one_calendar_year_ago(today)
    if value.date() < earliest:
        return value.replace(year=earliest.year, month=earliest.month, day=earliest.day)
    if value.date() > today:
        return value.replace(year=today.year, month=today.month, day=today.day)
    return value


def _date_field_arrow_rects(field_rect: pygame.Rect) -> tuple[pygame.Rect, pygame.Rect]:
    return (
        pygame.Rect(field_rect.left + 8, field_rect.top + 6, 34, field_rect.height - 12),
        pygame.Rect(field_rect.right - 42, field_rect.top + 6, 34, field_rect.height - 12),
    )


def choose_start_datetime(
    screen,
    font,
    clock,
    language: str,
    initial: datetime,
    now: datetime | None = None,
) -> datetime:
    """Let a gig-driver choose local year/month/day/hour/minute."""
    today = (now or datetime.now()).date()
    initial = _clamp_start_datetime(initial, today)
    values = [initial.year, initial.month, initial.day, initial.hour, initial.minute]
    labels = ("Vuosi", "Kuukausi", "Päivä", "Tunti", "Minuutti") if language == "fi" else (
        "Year", "Month", "Day", "Hour", "Minute",
    )
    selected = 0

    def adjusted(index: int, delta: int) -> None:
        earliest = _one_calendar_year_ago(today)
        limits = ((earliest.year, today.year), (1, 12), (1, 31), (0, 23), (0, 59))
        low, high = limits[index]
        values[index] = low + (values[index] - low + delta) % (high - low + 1)
        while True:
            try:
                clamped = _clamp_start_datetime(datetime(*values), today)
                values[:] = [clamped.year, clamped.month, clamped.day, clamped.hour, clamped.minute]
                break
            except ValueError:
                values[2] -= 1

    while True:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index in range(5):
                    rect = pygame.Rect(SCREEN_W // 2 - 190, 225 + index * 58, 380, 44)
                    if rect.collidepoint(event.pos):
                        selected = index
                        left_arrow, right_arrow = _date_field_arrow_rects(rect)
                        if left_arrow.collidepoint(event.pos):
                            adjusted(index, -1)
                        elif right_arrow.collidepoint(event.pos):
                            adjusted(index, 1)
                if pygame.Rect(SCREEN_W // 2 - 100, 540, 200, 48).collidepoint(event.pos):
                    return datetime(*values)
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                return initial
            if event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                selected = (selected + (1 if event.key in (pygame.K_DOWN, pygame.K_TAB) else -1)) % 5
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                adjusted(selected, 1 if event.key == pygame.K_RIGHT else -1)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return datetime(*values)

        screen.fill((18, 24, 32))
        title_text = "Valitse aloituspäivä ja -aika" if language == "fi" else "Choose starting date and time"
        title = font.render(title_text, True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 150)))
        for index, (label, value) in enumerate(zip(labels, values)):
            rect = pygame.Rect(SCREEN_W // 2 - 190, 225 + index * 58, 380, 44)
            pygame.draw.rect(screen, (45, 62, 78), rect, border_radius=5)
            if index == selected:
                pygame.draw.rect(screen, (255, 215, 95), rect, width=3, border_radius=5)
            left_arrow, right_arrow = _date_field_arrow_rects(rect)
            arrow_color = (255, 215, 95) if index == selected else (180, 198, 212)
            pygame.draw.polygon(
                screen,
                arrow_color,
                ((left_arrow.right - 9, left_arrow.top + 6),
                 (left_arrow.left + 9, left_arrow.centery),
                 (left_arrow.right - 9, left_arrow.bottom - 6)),
            )
            pygame.draw.polygon(
                screen,
                arrow_color,
                ((right_arrow.left + 9, right_arrow.top + 6),
                 (right_arrow.right - 9, right_arrow.centery),
                 (right_arrow.left + 9, right_arrow.bottom - 6)),
            )
            rendered = font.render(f"{label}: {value:02d}", True, (235, 240, 245))
            screen.blit(rendered, rendered.get_rect(center=rect.center))
        ok = pygame.Rect(SCREEN_W // 2 - 100, 540, 200, 48)
        pygame.draw.rect(screen, (55, 135, 85), ok, border_radius=5)
        ok_text = font.render("Aloita" if language == "fi" else "Start", True, (255, 255, 255))
        screen.blit(ok_text, ok_text.get_rect(center=ok.center))
        hint = pygame.font.SysFont(None, 20).render(
            "UP/DOWN: kenttä, LEFT/RIGHT: arvo, Enter: aloita"
            if language == "fi"
            else "UP/DOWN: field, LEFT/RIGHT: value, Enter: start",
            True, (150, 175, 195),
        )
        screen.blit(hint, hint.get_rect(center=(SCREEN_W // 2, 620)))
        pygame.display.flip()


def edit_city_list(screen, font, clock, config, cities_list: list[str], selected_idx: int, language: str) -> tuple[list[str], int]:
    catalog = load_city_catalog()
    editor_idx = selected_idx
    query = ""
    suggestion_idx = 0
    editing = True
    pygame.key.start_text_input()
    try:
        while editing:
            clock.tick(30)
            suggestions = city_suggestions(query, catalog=catalog)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    city_idx = _city_editor_item_at(ev.pos, len(cities_list), SCREEN_W)
                    if city_idx is not None:
                        editor_idx = city_idx
                        query = ""
                        suggestion_idx = 0
                        continue
                    picked_idx = _city_editor_suggestion_at(ev.pos, len(suggestions), SCREEN_W, SCREEN_H)
                    if picked_idx is not None:
                        selected_name = suggestions[picked_idx]
                        latitude, longitude = catalog[selected_name]
                        replace_city_in_config(config, editor_idx, selected_name, latitude, longitude)
                        save_config(config)
                        cities_list = list(cities_from_config(config)[0])
                        editing = False
                        continue
                if ev.type != pygame.KEYDOWN:
                    continue
                if ev.key == pygame.K_ESCAPE:
                    editing = False
                elif ev.key == pygame.K_BACKSPACE:
                    query = query[:-1]
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and suggestions:
                    selected_name = suggestions[suggestion_idx]
                    latitude, longitude = catalog[selected_name]
                    replace_city_in_config(config, editor_idx, selected_name, latitude, longitude)
                    save_config(config)
                    cities_list = list(cities_from_config(config)[0])
                    editing = False
                elif ev.key == pygame.K_UP and suggestions:
                    suggestion_idx = (suggestion_idx - 1) % len(suggestions)
                elif ev.key == pygame.K_DOWN and suggestions:
                    suggestion_idx = (suggestion_idx + 1) % len(suggestions)
                elif ev.unicode and ev.unicode.isprintable():
                    query += ev.unicode
                    suggestion_idx = 0
            draw_city_editor(
                screen, font, cities_list, editor_idx, query, suggestions, suggestion_idx,
                SCREEN_W, SCREEN_H, language,
            )
            pygame.display.flip()
    finally:
        pygame.key.stop_text_input()
    return cities_list, min(editor_idx, max(0, len(cities_list) - 1))


def choose_language(screen, font, clock, current_language: str = "fi") -> str:
    """Show the first-run language chooser."""
    import pygame

    selected = SUPPORTED_LANGUAGES.index(normalize_language(current_language))
    while True:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.MOUSEMOTION:
                hovered = _menu_item_at_y(event.pos[1], 280, 24, 31, len(SUPPORTED_LANGUAGES))
                if hovered is not None:
                    selected = hovered
                continue
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hovered = _menu_item_at_y(event.pos[1], 280, 24, 31, len(SUPPORTED_LANGUAGES))
                if hovered is not None:
                    return SUPPORTED_LANGUAGES[hovered]
                continue
            if event.type != pygame.KEYDOWN:
                continue
            if event.key in (pygame.K_LEFT, pygame.K_UP):
                selected = (selected - 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                selected = (selected + 1) % len(SUPPORTED_LANGUAGES)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                return SUPPORTED_LANGUAGES[selected]
            elif pygame.K_1 <= event.key <= pygame.K_9:
                index = event.key - pygame.K_1
                if index < len(SUPPORTED_LANGUAGES):
                    return SUPPORTED_LANGUAGES[index]

        language = SUPPORTED_LANGUAGES[selected]
        screen.fill((18, 24, 32))
        title = font.render(tr(language, "select_language"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen.get_width() // 2, 180)))
        for index, code in enumerate(SUPPORTED_LANGUAGES):
            color = (255, 215, 95) if index == selected else (210, 220, 230)
            label = font.render(f"{index + 1}. {LANGUAGE_NAMES[code]}", True, color)
            screen.blit(label, label.get_rect(center=(screen.get_width() // 2, 280 + index * 55)))
        hint = pygame.font.SysFont(None, 18).render(tr(language, "language_hint"), True, (150, 175, 195))
        screen.blit(hint, hint.get_rect(center=(screen.get_width() // 2, screen.get_height() - 80)))
        pygame.display.flip()


def confirm_outdated_cache(screen, font, clock, language: str) -> bool:
    """Ask before removing cache data created by an older release."""
    button_font = pygame.font.SysFont(None, 22)
    message_font = pygame.font.SysFont(None, 24)
    button_width, button_height = 130, 42
    selected = 0  # 0 = OK, 1 = Cancel - matches the other menus' selected-item highlight
    while True:
        clock.tick(30)
        screen_w, screen_h = screen.get_size()
        ok_rect = pygame.Rect(screen_w // 2 - button_width - 10, screen_h // 2 + 55, button_width, button_height)
        cancel_rect = pygame.Rect(screen_w // 2 + 10, screen_h // 2 + 55, button_width, button_height)

        def activate(index: int) -> bool:
            if index == 0:
                return True
            pygame.quit()
            sys.exit(0)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.MOUSEMOTION:
                if ok_rect.collidepoint(event.pos):
                    selected = 0
                elif cancel_rect.collidepoint(event.pos):
                    selected = 1
                continue
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                    selected = 1 - selected
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    return activate(selected)
                elif event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit(0)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if ok_rect.collidepoint(event.pos):
                    return activate(0)
                if cancel_rect.collidepoint(event.pos):
                    return activate(1)

        screen.fill((18, 24, 32))
        title = font.render(tr(language, "outdated_cache_title"), True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(screen_w // 2, screen_h // 2 - 80)))
        message = message_font.render(tr(language, "outdated_cache_message"), True, (210, 220, 230))
        screen.blit(message, message.get_rect(center=(screen_w // 2, screen_h // 2 - 25)))
        for index, (rect, key, color) in enumerate((
            (ok_rect, "ok", (55, 135, 85)),
            (cancel_rect, "cancel", (125, 65, 65)),
        )):
            pygame.draw.rect(screen, color, rect, border_radius=4)
            if index == selected:
                # Same selected-item accent color as the mode/pause menus.
                pygame.draw.rect(screen, (255, 215, 95), rect, width=3, border_radius=4)
            label = button_font.render(tr(language, key), True, (255, 255, 255))
            screen.blit(label, label.get_rect(center=rect.center))
        pygame.display.flip()
