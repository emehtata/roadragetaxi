from pyproj import Transformer

from theroadragetrip.borders import BorderWatch, country_at
from theroadragetrip.localization import tr

TO_M = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True).transform
TORNIO, HAPARANDA, SKIBOTN_NORWAY = TO_M(24.18, 65.85), TO_M(24.12, 65.83), TO_M(20.27, 69.39)


def test_the_border_at_tornio_and_the_neighbours():
    assert country_at(*TORNIO) == "FIN" and country_at(*HAPARANDA) == "SWE"
    assert country_at(*TO_M(19.94, 60.10)) == "FIN"  # Mariehamn: Aland is Finland
    assert country_at(*TO_M(28.70, 60.70)) == "RUS" and country_at(*TO_M(24.75, 59.44)) == "EST"
    assert country_at(*SKIBOTN_NORWAY) == "NOR"


def test_the_notice_comes_once_per_crossing_out_of_finland():
    watch = BorderWatch()
    assert watch.update(1.0, *TORNIO) is None
    assert watch.update(1.0, *HAPARANDA) == "SWE"
    assert watch.update(1.0, *HAPARANDA) is None  # still in Sweden: shown once
    assert watch.update(1.0, *TORNIO) is None
    assert watch.update(0.5, *HAPARANDA) is None  # checked once a second
    assert watch.update(0.5, *HAPARANDA) == "SWE"


def test_the_notice_names_the_country():
    assert (tr("en", "abroad", country=tr("en", "country_in_SWE"))
            == "You can drive in Sweden, but everything is Finnish here.")
    assert tr("fi", "abroad", country=tr("fi", "country_in_NOR")) == "Voit ajaa Norjassa, mutta täällä kaikki on suomalaista."
    assert tr("de", "abroad", country=tr("de", "country_in_RUS")) == "Du kannst in Russland fahren, aber hier ist alles finnisch."
