extends SceneTree


func _initialize() -> void:
    _render.call_deferred()


func _render() -> void:
    var background := ColorRect.new()
    background.size = Vector2(640,360)
    background.color = Color8(80,110,65)
    root.add_child(background)
    var layer := preload("res://wildlife.gd").new()
    root.add_child(layer)
    layer.scale = Vector2(12,12)
    var species := ["squirrel","small_bird","pigeon","hare","fox","moose","roe_deer"]
    for i in species.size():
        layer.animals.append({"id":i,"species":species[i],"position":Vector2(5+i*7,14),
            "heading":0.0,"state":"IDLE"})
    layer.queue_redraw()
    var entities := preload("res://entity_layer.gd").new()
    root.add_child(entities)
    var dog_canvas := Node2D.new()
    dog_canvas.scale = Vector2(12,12)
    root.add_child(dog_canvas)
    dog_canvas.draw.connect(func():
        entities._canvas = dog_canvas
        entities._dog(Vector2(10,24),Vector2(12,24),0.0,{"size":"medium","color":[160,110,60]})
    )
    dog_canvas.queue_redraw()
    var sounds := preload("res://animal_audio.gd").new()
    root.add_child(sounds)
    sounds.update(layer.animals,[[10,Vector2(5,5)]],Vector2(20,14),0.1,true)
    await process_frame
    await process_frame
    root.get_texture().get_image().save_png("/tmp/rrt-animal-audio.png")
    print("Rendered wildlife audio integration to /tmp/rrt-animal-audio.png")
    quit()
