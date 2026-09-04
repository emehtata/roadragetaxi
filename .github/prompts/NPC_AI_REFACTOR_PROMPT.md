# NPC-autojen päätöksenteon refaktorointiohje

## Tavoite

Erota yhden NPC-auton ajopäätökset `TrafficManager`ista. Refaktoroinnin pitää olla inkrementaalinen: nykyinen käyttäytyminen, testit ja julkiset API:t säilyvät.

## Nykyinen rakenne

- `src/theroadragetrip/traffic.py` sisältää `NPCCar`-datamallin ja monoliittisen `TrafficManager.update()`-loopin.
- `CarAI = NPCCar` on nykyinen yhteensopivuusalias.
- Jo erotetut moduulit:
  - `traffic_maneuvers.py`: käännösten sampled trajectory -logiikka.
  - `traffic_collisions.py`: NPC-NPC- ja static obstacle -törmäykset.
  - `traffic_lights.py`: `TrafficLightManager`.
  - `traffic_intersections.py`: `IntersectionManager` ja risteysvaraukset.
  - `traffic_static.py`: rakennus- ja puuesteiden spatial-indexit.
  - `traffic_routes.py`: reittigraafi ja shortest-path-haku.
- `TrafficManager` toimii jatkossakin maailman koordinaattorina.

## Vastuunjako

### TrafficManager omistaa

- NPC-listan, spawnin ja despawnin.
- Spatial-gridit ja nearby-haut.
- Liikennevalot, stop/yield-merkit ja risteysvaraukset.
- Reittigraafin ja reittipalvelun käytön.
- Törmäysten resolvoinnin.
- Päivitysjärjestyksen.
- Taxi-, resident- ja police-integraation.

### CarAI omistaa

- Yhden auton liikennetilanteen tulkinnan.
- Ajaako, jarruttaako vai pysähtyykö auto.
- Tavoitenopeuden ja tavoitelane-offsetin.
- Ohitus- ja väistöpäätöksen.
- Käännökseen valmistautumisen.
- Seuraavan reitin valmistelun autokohtaisesti.
- Auton `action`, `reason` ja liikennetilan päätöksen.

CarAI ei omista maailmaa eikä muuta auton sijaintia suoraan.

## Ensimmäinen toteutus

Lisää ensin päätöksen datamalli:

```python
@dataclass
class CarDecision:
    action: str
    target_speed: float
    target_lane_offset: float
    must_stop: bool = False
    reason: str = ""
```

Lisää autolle havaintokonteksti:

```python
@dataclass
class TrafficContext:
    nearby_npcs: List[NPCCar]
    next_way: Optional[Tuple[Way, int, int]]
    signal_state: str
    stop_distance: Optional[float]
    junction_blocked: bool
    yield_slowdown: float
    proposed_blocker: Optional[NPCCar]
```

Päätösrajapinta:

```python
def decide(
    npc: NPCCar,
    context: TrafficContext,
    dt: float,
) -> CarDecision:
    ...
```

Aluksi päätöslogiikka voi olla module-level-funktio `traffic_ai.py`:ssä. Älä rakenna vielä laajaa luokkahierarkiaa.

## Päivitysloopin tavoitemuoto

```python
for npc in self.npcs:
    if not self._npc_update_is_due(npc):
        continue
    context = self._build_traffic_context(npc)
    decision = decide(npc, context, dt)
    self._apply_decision(npc, decision, dt)

for npc in self.npcs:
    self._move_npc(npc, dt)

self._resolve_npc_collisions()
self._update_crashed_npcs()
```

Tavoitesääntö:

- `decide()` ei muuta `x`-, `y`- tai `heading`-arvoja.
- Liikemalli vastaa sijainnista, steeringistä ja segmentin vaihdosta.
- `TrafficManager` vastaa autojen välisistä konflikteista ja maailman tilasta.

## Siirtämisjärjestys

1. Lisää `CarDecision` ja `TrafficContext`.
2. Irrota nykyisestä `update()`-metodista päätösosuus yhdeksi `decide_npc()`-funktioksi.
3. Kutsu funktiota nykyisestä loopista.
4. Lisää päätöskohtaiset unit-testit.
5. Siirrä funktio `traffic_ai.py`:hen.
6. Pilko tarvittaessa seuraaviin pieniin funktioihin:
   - `prepare_route()`
   - `choose_lane_offset()`
   - `update_blocked_state()`
   - `decide_speed()`
7. Erottele liikemalli vasta päätöslogiikan jälkeen.
8. Säilytä `CarAI = NPCCar`, kunnes ulkopuoliset API:t voidaan turvallisesti päivittää.

## Testit

Lisää vähintään nämä päätöstestit:

- Punainen valo -> `must_stop`.
- Vapaa tie -> `driving`.
- Liikkuva blokkeri -> `waiting` tai `braking`.
- Pitkä blokkaus -> `overtaking`.
- Aktiivinen turn trajectory -> ei normaalia lane-päätöstä.
- `crashed` tai `fallen` -> `crashed`, nopeus nolla.
- Risteysvaraus estää sisäänajon.

Testaa ilman Pygamea aina kun mahdollista.

## Säilytettävät rajat

Älä siirrä CarAI:hin:

- `request_enter()`- tai reservation-logiikkaa.
- NPC spatial-gridin rakennusta.
- Törmäysten resolvointia.
- Staattisten esteiden indeksointia.
- Spawn/despawn-logiikkaa.
- Taxi-, resident- tai police-tilan omistajuutta.
- Maailman reittigraafin rakentamista.

Älä tee big-bang-rewritea. Jokaisen extractionin jälkeen aja ensin lähimmät testit, sitten koko suite.

## Validointi

Käytä aina projektin virtuaaliympäristöä:

```bash
source .venv/bin/activate
PYTHONPATH=src:. pytest -q
PYTHONPATH=src python -m compileall -q src/theroadragetrip tests utils
git diff --check
```

Liikennekäyttäytymisen headless-audit:

```bash
source .venv/bin/activate
PYTHONPATH=src:. python -m utils.autoplay_audit --steps 600 --seed 42
```

## Työskentelysäännöt

- Säilytä nykyiset wrapperit ja import-polut.
- Suosi callbackeja ja pieniä pureja funktioita.
- Älä lisää protokollia, factoryja tai strategiahierarkioita ilman todellista tarvetta.
- Älä muuta liikennekäyttäytymistä extractionin yhteydessä.
- Korjaa vain tähän refaktorointiin liittyvät virheet.
- Päivitä `README.md`, jos käyttäjälle näkyviä komentoja tai API:eja muuttuu.
- Älä tee committia automaattisesti.
