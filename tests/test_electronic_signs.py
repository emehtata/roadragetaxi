import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from theroadragetrip import electronic_signs as es
from theroadragetrip.digitraffic_road import DigitrafficClient, LiveRoadworks, RoadDataService, tile_of
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid

FIXTURE = Path(__file__).parent / 'fixtures/digitraffic_variable_signs.json'
NOW = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)


def feature(**changes):
    value = copy.deepcopy(json.loads(FIXTURE.read_text())['features'][0])
    value['properties'].update(changes)
    return value


def parse(*features):
    return es.parse_signs({'features': list(features)})


def test_recorded_speed_warning_and_information_signs():
    signs = es.parse_signs(json.loads(FIXTURE.read_text()))
    assert len(signs) == 3
    assert signs[0]['speed_limit_kmh'] == 100 and signs[1]['code'] == '165'
    assert signs[2]['text'] == ['SILTATYÖ'] and signs[2]['road'] == '1'


@pytest.mark.parametrize('changes', [dict(reliability='MALFUNCTION'), dict(type='UNKNOWN'), dict(displayValue='abc'),
    dict(displayValue='-10'), dict(displayValue='999'), dict(effectDate='bad'), dict(effectDate='2026-10-28T09:00:00'),
    dict(textRows=None), dict(textRows=['bad']), dict(roadAddress='unknown')])
def test_invalid_or_faulty_signs_are_ignored(changes):
    assert parse(feature(**changes)) == []


def test_coordinates_blank_display_and_text_validation():
    for coords in [[float('nan'), 60], [180, 100], ['24', 60], []]:
        value = feature(); value['geometry']['coordinates'] = coords
        assert parse(value) == []
    assert es.parse_signs(None) == []
    sign = parse(feature(type='INFORMATION', displayValue='', textRows=[
        {'screen': 1, 'rowNumber': 2, 'text': '[tie_4] +5 min'},
        {'screen': 1, 'rowNumber': 1, 'text': 'ILMA +10 Â°C'},
        {'screen': 2, 'rowNumber': 1, 'text': 'OTHER SCREEN'}]))[0]
    assert sign['text'] == ['ILMA +10 °C', '[tie_4] +5 min']


def test_nearby_signs_follow_time_same_road_surface_level_and_distance():
    signs = parse(feature(), feature(id='future', effectDate='2027-01-01T00:00:00Z'),
                  feature(id='other-road', roadAddress='4 1 1'), feature(id='far'))
    signs = [dict(s, x=10 if s['id'] != 'far' else 1000, y=0) for s in signs]
    road = Way([(0, 0), (100, 0)], 'primary', 4, ref='E18;1')
    car = Car(0, 0, 0, 0)
    assert len(es.nearby_signs(signs, car, road, NOW)) == 1
    assert es.nearby_signs(signs, car, road, NOW)[0]['distance_m'] == 10
    for attr, value in [('layer', 1), ('map_level', -1)]:
        setattr(car, attr, value)
        assert es.nearby_signs(signs, car, road, NOW) == []
        setattr(car, attr, 0)
    blank = dict(signs[0], effect_date='2026-10-28T08:00:00Z', _effect_time=NOW.replace(hour=8).timestamp(), speed_limit_kmh=None)
    assert es.nearby_signs(signs + [blank], car, road, NOW) == []


def test_history_uses_game_day_and_does_not_leak_future_values():
    latest = feature(effectDate='2026-10-28T10:00:00Z', displayValue='80')
    calls = []
    class Client:
        def get_json(self, path, params=None, **kwargs):
            calls.append((path, params))
            return {'features': [latest]} if path.endswith('/signs') else [
                {'effectDate':'2026-10-28T08:00:00Z','displayValue':'60','rows':[]},
                {'effectDate':'2026-10-28T10:00:00Z','displayValue':'80','rows':[]}]
    signs, complete = es.fetch_signs(Client(), [tile_of(23.129905, 60.417834)], NOW)
    assert complete and calls[-1][1]['effectiveDate'] == '2026-10-28'
    signs = [dict(s, x=0, y=0) for s in signs]
    road = SimpleNamespace(ref='1')
    assert es.nearby_signs(signs, Car(0,0,0,0), road, NOW)[0]['speed_limit_kmh'] == 60
    later = NOW.replace(hour=11)
    updated, _ = es.fetch_signs(Client(), [tile_of(23.129905, 60.417834)], later)
    updated = [dict(s, x=0, y=0) for s in updated]
    assert es.nearby_signs(updated, Car(0,0,0,0), road, later)[0]['speed_limit_kmh'] == 80


@pytest.mark.parametrize('database', [False, True])
def test_sign_cache_refreshes_while_roadwork_cache_stays_permanent(tmp_path, database):
    now = [0.0]; calls = []
    def opener(url, headers):
        calls.append(url)
        return b'{"features":[]}'
    client = DigitrafficClient(tmp_path / 'cache.sqlite' if database else None, opener, clock=lambda: now[0])
    client.get_json('/signs', max_age_s=60)
    client.get_json('/signs', max_age_s=60)
    assert len(calls) == 1
    if database:
        client._db.execute("UPDATE responses SET fetched_at='2020-01-01T00:00:00+00:00'")
        client._db.commit()
    else:
        now[0] = 61
    client.get_json('/signs', max_age_s=60)
    assert len(calls) == 2
    client.get_json('/signs')
    assert len(calls) == 2


def test_background_service_loads_signs_and_publishes_projected_nearby_readings():
    data = json.dumps({'features': [feature()]}).encode()
    client = DigitrafficClient(None, lambda url, headers: data if 'variable-sign' in url else b'{"features":[]}')
    service = RoadDataService(client, lambda x,y:(23.13,60.42))
    try:
        service.request(0,0,NOW)
        service.wait_idle(3)
        assert service.variable_signs
        live = LiveRoadworks(service, lambda lon,lat:(10,0))
        road = Way([(0,0),(100,0)],'primary',4,ref='1')
        live.update(0,0,NOW,NOW,1,SpatialWayGrid([road]))
        assert live.electronic_signs_near(Car(0,0,0,0), road)[0]['speed_limit_kmh'] == 100
    finally:
        service.close()


def test_changes_and_blank_readings_apply_inside_a_query_window():
    latest = feature(effectDate='2026-10-28T09:07:00Z', displayValue='')
    class Client:
        def get_json(self, path, params=None, **kwargs):
            return {'features':[latest]} if path.endswith('/signs') else [
                {'effectDate':'2026-10-28T08:00:00Z','displayValue':'60'},
                {'effectDate':'2026-10-28T09:05:00Z','displayValue':'80'},
                {'effectDate':'2026-10-28T09:07:00Z','displayValue':''}]
    signs, _ = es.fetch_signs(Client(), [tile_of(23.129905,60.417834)], NOW)
    signs = [dict(s,x=0,y=0) for s in signs]
    car, road = Car(0,0,0,0), SimpleNamespace(ref='1')
    assert es.nearby_signs(signs,car,road,NOW)[0]['speed_limit_kmh'] == 60
    assert es.nearby_signs(signs,car,road,NOW.replace(minute=6))[0]['speed_limit_kmh'] == 80
    assert es.nearby_signs(signs,car,road,NOW.replace(minute=8)) == []


def test_only_nearest_of_each_sign_type_is_displayed():
    signs = es.parse_signs(json.loads(FIXTURE.read_text()))
    signs = [dict(s,road='1',x=10,y=0) for s in signs]
    farther = dict(signs[0],id='farther-speed',x=50)
    rows = es.nearby_signs(signs+[farther],Car(0,0,0,0),SimpleNamespace(ref='1'),NOW)
    assert len(rows) == 3 and {r['type'] for r in rows} == {'SPEEDLIMIT','WARNING','INFORMATION'}
    assert all(r['id'] != 'farther-speed' for r in rows)
