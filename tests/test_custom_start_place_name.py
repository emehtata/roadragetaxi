from types import SimpleNamespace

from theroadragetrip.osm.models import Place
from theroadragetrip.server import SimulationServer


def test_custom_start_names_nearest_town_not_catalog_city():
    places = [Place(0, 0, "Far", "town"), Place(90, 0, "Utajärvi", "village"), Place(100, 0, "Kylä", "suburb")]
    server = SimpleNamespace(args=SimpleNamespace(bbox="1,2,3,4", place_name=None), chosen_city="Oulu",
                             world=SimpleNamespace(places=places), car=SimpleNamespace(x=100, y=0))
    assert SimulationServer._place_name(server) == "Utajärvi"
    server.args.bbox = None
    assert SimulationServer._place_name(server) == "Oulu"
    server.args.bbox, server.args.place_name = "1,2,3,4", "Juorkuna"
    assert SimulationServer._place_name(server) == "Juorkuna"
