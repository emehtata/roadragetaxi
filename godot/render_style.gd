## Colours and sizes the Godot client draws with - presentation data, not
## game rules. tests/test_godot_render_style.py checks the
## train palette against train_compositions.PROFILES.
class_name RenderStyle
extends RefCounted

# Vehicles
const OUTLINE := Color8(20, 20, 20)
const CABIN := Color8(30, 35, 45)
const WINDSHIELD := Color8(52, 74, 92)  # car glass from above: a dark blue sheen
const TAXI_SIGN := Color8(240, 220, 20)
const TAXI_BODY := Color8(235, 195, 30)
const HEADLIGHT := Color8(255, 255, 230)
const HEADLIGHT_OFF := Color8(120, 120, 108)  # ENGINE_OFF_HEADLIGHT_COLOR
const TAILLIGHT := Color8(230, 30, 30)
const TAILLIGHT_OFF := Color8(105, 28, 28)  # ENGINE_OFF_TAILLIGHT_COLOR
const BRAKE_LIGHT := Color8(255, 0, 0)
const REVERSE_LIGHT := Color8(245, 245, 235)
const TURN_SIGNAL := Color8(255, 170, 20)
const TURN_SIGNAL_PERIOD_S := 0.9  # on for the first half of each period
const TRUCK_WINDSHIELD := Color8(35, 48, 58)
const SMOKE := Color(180 / 255.0, 180 / 255.0, 180 / 255.0)
const SMOKE_MAX_ALPHA := 160 / 255.0

# trains.py TRAIN_WIDTH_M;
# train_compositions.py PROFILES: profile -> [body, pattern or null]
const TRAIN_WIDTH_M := 3.2
const TRAIN_ROOF_LINE := Color8(30, 30, 30)
const TRAIN_PROFILES := {
	"locomotive": [Color8(12, 48, 24), Color8(240, 240, 235)],
	"standard": [Color8(46, 125, 60), null],
	"restaurant": [Color8(46, 125, 60), Color8(245, 245, 240)],
	"family": [Color8(96, 170, 92), null],
	"pet": [Color8(34, 100, 70), null],
	# Trams (trams.py): their sections, a light roof stripe down the middle.
	"tram_helsinki": [Color8(20, 140, 70), Color8(235, 240, 235)],
	"tram_tampere": [Color8(185, 25, 40), Color8(240, 240, 240)],
}
const TRAM_WIDTH_M := 2.4  # trams.py TRAM_WIDTH_M

# Pedestrians (appearance isn't sent: these are the defaults, with the
# pedestrian's own colour as clothing)
const PED_SHADOW := Color8(20, 20, 20)
const PED_LEGS := Color8(35, 35, 45)
const PED_HEAD := Color8(238, 185, 145)
const PED_HAIR := Color8(20, 20, 20)
const PED_INDOORS := Color8(235, 235, 235)
const CURSE_TEXT := Color8(240, 40, 40)
const CURSE_BORDER := Color8(200, 30, 30)

# Navigation: the job target, the compass
const PICKUP := Color8(255, 200, 0)
const BOOKED_CUSTOMER := Color8(90, 200, 255)
const LIGHTNING_FLASH := Color8(220, 228, 242)
const LIGHTNING_FLASH_MAX_ALPHA := 145.0 / 255.0
const DROPOFF := Color8(50, 220, 100)
const CUSTOMER_COLOR := Color8(240, 220, 60)  # TaxiPassenger.ped_color default
const NAUSEA_TEXT := Color8(210, 35, 35)

# Weather: wet roads, puddles
const WET_DARKEN := Color8(8, 10, 14)
const WET_DARKEN_MAX_ALPHA := 90 / 255.0
const WET_SHEEN := Color8(205, 215, 230)
const WET_SHEEN_MAX_ALPHA := 12 / 255.0
const WET_SHEEN_MIN_WETNESS := 0.15
const PUDDLE_CHANCE_PER_WAY := 0.4  # per PUDDLE_STRETCH_M
const PUDDLE_STRETCH_M := 8.0  # ~5 puddles per 100 m of street at 0.4
const PUDDLE_MIN_RADIUS_M := 0.6
const PUDDLE_MAX_RADIUS_M := 2.2
const PUDDLE_REVEAL_MIN := 0.2
const PUDDLE_REVEAL_MAX := 0.75
# Brighter than a navy (32, 40, 54) at 150: on a road already darkened by
# the wetness, that all but vanished. Standing water reflects the sky.
const PUDDLE_COLOR := Color8(92, 108, 128)
const PUDDLE_MAX_ALPHA := 170 / 255.0
const PUDDLE_SHAPE_POINTS := 7
const PUDDLE_SHAPE_JITTER := 0.35


## Is a turn signal lamp lit at this point of its blink (elapsed % 0.9 < 0.45)?
static func signal_lit(elapsed: float) -> bool:
	return fmod(elapsed, TURN_SIGNAL_PERIOD_S) < TURN_SIGNAL_PERIOD_S * 0.5


## Wet-road overlay strengths for a wetness 0..1: [darken alpha, sheen alpha].
static func wet_alphas(wetness: float) -> Array:
	var sheen_wetness := maxf(0.0, wetness - WET_SHEEN_MIN_WETNESS) / (1.0 - WET_SHEEN_MIN_WETNESS)
	return [WET_DARKEN_MAX_ALPHA * clampf(wetness, 0.0, 1.0), WET_SHEEN_MAX_ALPHA * sheen_wetness]


## A puddle's visible strength 0..1 at this wetness.
static func puddle_strength(wetness: float, reveal: float) -> float:
	return clampf((wetness - reveal) / (1.0 - reveal), 0.0, 1.0)

# The navigation route
const ROUTE_EDGE := Color8(60, 45, 5)
const ROUTE := Color8(255, 215, 35)

# The rage shout, red on white
const SHOUT := Color8(240, 40, 40)
const SHOUT_BORDER := Color8(200, 30, 30)
