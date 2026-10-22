from theroadragetrip.activities.plugins.tennis import rally_spot


def test_rally_spots_stay_inside_the_court_and_vary_in_depth():
    for side in (0, 1):
        spots = [rally_spot(side, turn) for turn in range(200)]
        assert all(.29 < abs(u) <= .42 and abs(v) < .3 for u, v in spots)
        assert all((u < 0) == (side == 0) for u, _ in spots)  # each keeps their own half
        depths = [abs(u) for u, _ in spots]
        assert max(depths) - min(depths) > .08
