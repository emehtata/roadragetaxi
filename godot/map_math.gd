## World metres (x east, y north) -> this client's canvas (relative to the
## map origin, y down).
class_name MapMath


static func point(origin: Vector2, x: float, y: float) -> Vector2:
	return Vector2(x - origin.x, -(y - origin.y))
