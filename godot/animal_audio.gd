## Short positional calls from existing wildlife and owned dogs.
extends Node

const Paths := preload("res://paths.gd")
const PLAYERS := 4
const RANGES := {"squirrel": 30.0, "small_bird": 65.0, "pigeon": 40.0,
    "hare": 45.0, "fox": 120.0, "moose": 100.0, "roe_deer": 100.0, "dog": 100.0}
const INTERVALS := {"squirrel": 35.0, "small_bird": 12.0, "pigeon": 25.0,
    "hare": 60.0, "fox": 65.0, "moose": 90.0, "roe_deer": 75.0, "dog": 30.0}

var _streams := {}
var _players: Array = []
var _sources: Array = []
var _due := {}
var _clock := 0.0


func _ready() -> void:
    for species in RANGES:
        var path := Paths.package_path("assets/audio/animals/%s.ogg" % species)
        var stream := AudioStreamOggVorbis.load_from_file(path)
        if stream != null:
            _streams[species] = stream
    for i in PLAYERS:
        var player := AudioStreamPlayer2D.new()
        player.bus = "Environment"
        player.attenuation = 0.0
        player.max_distance = 100000.0
        player.panning_strength = 0.6
        add_child(player)
        _players.append(player)
        _sources.append("")


static func gain(species: String, distance_m: float) -> float:
    var limit: float = RANGES.get(species, 0.0)
    if limit <= 0.0 or distance_m >= limit:
        return 0.0
    return pow(1.0 - clampf((distance_m - 4.0) / (limit - 4.0), 0.0, 1.0), 2.0)


func clear() -> void:
    for player in _players:
        player.stop()
    _sources.fill("")
    _due.clear()


## dog rows: [stable owner id, interpolated layer position].
func update(animals: Array, dogs: Array, listener: Vector2, delta: float, surface: bool) -> void:
    _clock += delta
    if not surface:
        clear()
        return
    var nearby := {}
    for animal in animals:
        var species: String = animal.species
        if species == "hare" and animal.state != "FLEE":
            continue
        var at: Vector2 = animal.position
        if gain(species, at.distance_to(listener)) > 0.0:
            nearby["wildlife:%s" % animal.id] = [species, at]
    for dog in dogs:
        if gain("dog", dog[1].distance_to(listener)) > 0.0:
            nearby["dog:%s" % dog[0]] = ["dog", dog[1]]
    for id in _due.keys():
        if not nearby.has(id):
            _due.erase(id)
    for i in _players.size():
        var id: String = _sources[i]
        if not nearby.has(id) or not _players[i].playing:
            _players[i].stop()
            _sources[i] = ""
        else:
            _position(i, nearby[id], listener)
    for id in nearby:
        if not _due.has(id):
            _due[id] = _clock + 2.0 + float(absi(hash(id)) % 600) / 100.0
        if _clock < _due[id] or _sources.has(id):
            continue
        var species: String = nearby[id][0]
        var slot := _sources.find("")
        if slot < 0:
            break
        _due[id] = _clock + float(INTERVALS[species]) * randf_range(0.8, 1.4)
        if not _streams.has(species):
            continue
        _sources[slot] = id
        _players[slot].stream = _streams[species]
        _players[slot].pitch_scale = randf_range(0.94, 1.06)
        _position(slot, nearby[id], listener)
        _players[slot].play()


func _position(index: int, source: Array, listener: Vector2) -> void:
    _players[index].position = source[1]
    _players[index].volume_db = -10.0 + linear_to_db(maxf(0.00001, gain(source[0], source[1].distance_to(listener))))
