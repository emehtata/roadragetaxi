extends SceneTree


func _initialize() -> void:
    _test.call_deferred()


func _test() -> void:
    var sounds := preload("res://animal_audio.gd").new()
    root.add_child(sounds)
    assert(sounds._streams.size() == 9, "all nine generated calls must load")
    assert(sounds._players.size() == 4, "playback pool must stay bounded")
    assert(sounds.gain("dog", 0) == 1.0 and sounds.gain("dog", 100) == 0.0)
    assert(sounds.gain("small_bird", 20) > sounds.gain("small_bird", 50))
    var animal := {"id":1,"species":"crow","position":Vector2(10,0),"state":"IDLE"}
    var dog := [2,Vector2(-10,0)]
    sounds.update([animal],[dog],Vector2.ZERO,0.1,true)
    sounds._due["wildlife:1"] = 0.0
    sounds._due["dog:2"] = 0.0
    sounds.update([animal],[dog],Vector2.ZERO,0.1,true)
    assert(sounds._sources.has("wildlife:1") and sounds._sources.has("dog:2"))
    var slot: int = sounds._sources.find("wildlife:1")
    animal.position = Vector2(20,0)
    sounds.update([animal],[dog],Vector2.ZERO,0.1,true)
    assert(sounds._players[slot].position == Vector2(20,0), "calling animals move spatially")
    sounds.update([],[],Vector2.ZERO,0.1,true)
    assert(sounds._sources.all(func(id):return id == "") and sounds._due.is_empty())
    sounds.update([animal],[dog],Vector2.ZERO,0.1,false)
    assert(sounds._sources.all(func(id):return id == ""), "surface calls stop underground")
    sounds.update([{"id":3,"species":"hare","position":Vector2.ZERO,"state":"IDLE"}],[],Vector2.ZERO,0.1,true)
    assert(sounds._due.is_empty(), "quiet hares do not call")
    var flock: Array = []
    for i in 128:
        flock.append({"id":i,"species":"small_bird","position":Vector2.ZERO,"state":"FEED"})
    sounds.update(flock,[],Vector2.ZERO,0.1,true)
    for id in sounds._due:
        sounds._due[id] = 0.0
    sounds.update(flock,[],Vector2.ZERO,0.1,true)
    assert(sounds._sources.filter(func(id):return id != "").size() == 4, "large flocks cannot exceed the voice pool")
    sounds.clear()
    var entities := preload("res://entity_layer.gd").new()
    entities.origin = Vector2(100,200)
    entities._frame = {"a":{"pedestrians":[{"id":12,"dog":{"x":110,"y":220}}]},
        "b":{"pedestrians":[{"id":12,"dog":{"x":114,"y":224}}]},"t":0.5}
    assert(entities.dogs() == [[12,Vector2(12,-22)]], "dog audio follows world-to-layer interpolation")
    entities.free()
    print("Animal audio tests passed: nine assets, spatial playback, cooldowns, source cleanup and underground silence")
    sounds.queue_free()
    await process_frame
    quit()
