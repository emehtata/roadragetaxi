# Dog walking

Dog walking is an ordinary pedestrian activity (`dog_walking`), not a second
population system. The owner uses the existing pedestrian network at normal
walking speed. Morning and evening selection peaks come from the simulation
clock; nearby parks and green areas increase the activity's weight.

Each active owner holds one lightweight dog record. The dog follows a smoothed
offset behind the owner, occasionally sniffs while the owner pauses, and is
clamped to a 2.8 m leash. Ending or removing the activity removes the dog with
its owner. At most 12 owned dogs may be active. Dogs have no collision or
physics body and never enter the wildlife population.

The existing pedestrian network payload carries the dog with its owner. Godot
interpolates it between server states and draws the dog and leash in the shared
pedestrian canvas, so there are no per-dog scene nodes or per-frame network
lookups.

Map-data limitation: green-space data only adjusts activity preference. The
owner always follows the existing pedestrian network; this feature does not
create routes through unmapped lawns or add a separate land-use pathfinder.
