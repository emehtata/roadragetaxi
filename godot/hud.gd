## The player's HUD: money, speed, game time, weather, the fare and the
## simulation's notice, all read from the state being shown. Only formats
## what Python decided (`values` is a pure state -> text mapping); no game
## rules here. F3 toggles the developer readout (main.gd fills it).
extends Control

@onready var _money: Label = %Money
@onready var _speed: Label = %Speed
@onready var _clock: Label = %Clock
@onready var _weather: Label = %Weather
@onready var _fare: Label = %Fare
@onready var _notice: Label = %Notice
@onready var _hint: Label = %Hint


func show_state(state: Dictionary) -> void:
	var text := values(state)
	_money.text = text["money"]
	_speed.text = text["speed"]
	_clock.text = text["clock"]
	_weather.text = text["weather"]
	_fare.text = text["fare"]
	_notice.text = text["notice"]
	_notice.visible = text["notice"] != ""
	_hint.text = text["hint"]


## Display text for one state. Every field is optional: a missing one shows
## a placeholder instead of failing.
static func values(state: Dictionary) -> Dictionary:
	var player: Dictionary = state.get("player", {})
	var taxi: Dictionary = state.get("taxi", {})
	var weather: Dictionary = state.get("weather", {})
	var on_foot: bool = state.get("on_foot", true)
	var text := {}
	text["money"] = "%.2f €" % (taxi["balance_cents"] / 100.0) if taxi.has("balance_cents") else "– €"
	text["speed"] = "on foot" if on_foot else ("%d km/h" % roundi(absf(player.get("speed", 0.0)) * 3.6))
	if state.has("game_time_seconds"):
		var minutes := int(state["game_time_seconds"] / 60.0)
		text["clock"] = "%02d:%02d" % [minutes / 60 % 24, minutes % 60]
	else:
		text["clock"] = "--:--"
	if weather.has("weather_type"):
		text["weather"] = "%s, road %d%% wet" % [str(weather["weather_type"]).capitalize(), roundi(weather.get("wetness", 0.0) * 100)]
	else:
		text["weather"] = ""
	var passenger = taxi.get("current_passenger")
	if passenger == null or typeof(passenger) != TYPE_DICTIONARY:
		text["fare"] = "No fare - %d done" % taxi.get("completed_fares", 0)
	else:
		var who: String = passenger.get("name", "Passenger")
		match taxi.get("state", ""):
			"PICKUP":
				text["fare"] = "Pick up %s at %s" % [who, passenger.get("pickup", {}).get("address", "?")]
			"WALKING":
				text["fare"] = "%s is walking to the taxi" % who
			"DROPOFF":
				text["fare"] = "Drive %s to %s" % [who, passenger.get("dropoff", {}).get("address", "?")]
			_:
				text["fare"] = who
	text["notice"] = str(taxi.get("notification_msg", "")) if taxi.get("notification_timer", 0.0) > 0.0 else ""
	if on_foot:
		text["hint"] = "F get in the taxi · WASD walk · P phone"
	elif not player.get("engine_on", true):
		text["hint"] = "E start the engine · F get out · P phone"
	else:
		text["hint"] = "WASD drive · F get out · E engine · P phone · +/- zoom"
	return text
