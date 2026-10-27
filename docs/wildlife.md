# Wildlife ambience

Wildlife is a client-side Godot visual layer. It does not exist in Python simulation
state and therefore cannot collide with vehicles, affect routing, damage, traffic
rules, fares, or finances.

Each loaded map chunk owns a deterministic, bounded set of animal drawing records.
Unloading the chunk removes them; refreshing it preserves their positions. One
canvas node draws the whole population, with no physics bodies or per-animal nodes.
Small-bird records draw five-member flocks and pigeon records draw groups of three,
so birds remain visible without multiplying simulation work.
Movement uses a 0.1-second fixed step and distant animals are not updated.

The streamed chunks currently retain building and tree geometry but not original
OSM land-use names. Habitat therefore uses local building/tree counts: dense built
chunks are urban, mixed chunks suburban, and tree-rich lightly built chunks rural.
It never treats distance from the city centre as forest evidence. This fallback can
misclassify treeless open countryside and unusually wooded city blocks; preserving
land-use identifiers in the chunk format would be the appropriate later upgrade.
Where tree points are available, woodland animals spawn near those real visible
trees rather than uniformly across the mostly off-screen chunk.

The initial visuals are replaceable top-down vector silhouettes in
`godot/wildlife.gd`; no external assets are required. Public layer properties set
density, the wildlife-only population cap, activity distance, species weights, and
vehicle reactions.
