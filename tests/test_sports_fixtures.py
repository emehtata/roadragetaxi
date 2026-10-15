from datetime import datetime, timedelta, timezone

import pytest

from theroadragetrip.sports_fixtures import active_match_crowds, load_sports_fixtures


def test_committed_fixtures_cover_both_competitions_and_seasons():
    matches = load_sports_fixtures()
    counts = {(competition, season): sum(
        match["competition"] == competition and match["season"] == season for match in matches
    ) for competition, season in (
        ("liiga", "2025-26"), ("liiga", "2026-27"),
        ("veikkausliiga", "2025"), ("veikkausliiga", "2026"),
    )}
    assert counts == {
        ("liiga", "2025-26"): 540, ("liiga", "2026-27"): 544,
        ("veikkausliiga", "2025"): 177, ("veikkausliiga", "2026"): 177,
    }
    assert all(match["home_team"] and match["away_team"] and match["venue"]["name"] for match in matches)
    hockey = next(match for match in matches if match["sport"] == "ice_hockey")
    start = datetime.fromisoformat(hockey["start"].replace("Z", "+00:00"))
    crowd_start = datetime.fromisoformat(hockey["crowd_start"].replace("Z", "+00:00"))
    crowd_end = datetime.fromisoformat(hockey["crowd_end"].replace("Z", "+00:00"))
    assert start - crowd_start == timedelta(hours=1)
    assert crowd_end - start == timedelta(hours=3)


def test_active_match_crowds_uses_the_saved_crowd_window():
    fixtures = ({"id": "now", "crowd_start": "2026-10-15T15:00:00Z", "crowd_end": "2026-10-15T18:00:00Z"},)
    assert [match["id"] for match in active_match_crowds(
        datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc), fixtures
    )] == ["now"]
    assert active_match_crowds(datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc), fixtures) == []
    with pytest.raises(ValueError, match="timezone-aware"):
        active_match_crowds(datetime(2026, 10, 15, 17, 0), fixtures)
