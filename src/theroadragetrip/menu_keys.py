"""Shared keyboard shortcuts used by menu input and rendering."""

# E and F are city-menu commands (edit list and force map refresh), so they
# must never also be displayed as direct city selectors.
CITY_MENU_COMMAND_KEYS = frozenset({"E", "F"})
CITY_MENU_KEYS = "1234567890" + "".join(
    letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if letter not in CITY_MENU_COMMAND_KEYS
)
