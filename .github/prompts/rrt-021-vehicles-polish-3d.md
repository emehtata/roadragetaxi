# Task: Complete Vehicle Visual Quality Overhaul

The game now features a proper 3D rendering environment in Godot.

Human and animal characters are being upgraded to high-quality stylized realism.

Now apply the same quality ambitions to ALL vehicles in the game.

Current vehicles look overly angular, boxy and primitive. Cars in particular lack realistic body shapes, proportions, surface details and material quality.

The goal is to transform every vehicle into a visually convincing, professionally designed 3D game model.

## 1. Visual Direction

Target style:

HIGH-QUALITY STYLIZED AUTOMOTIVE REALISM.

Vehicles should look like believable real-world vehicles, with slightly stylized artistic presentation.

The visual quality should be comparable to modern commercial driving and open-world games.

Avoid:
- Primitive box-shaped cars.
- Flat vehicle surfaces.
- Excessively angular bodywork.
- Simple rectangular windows.
- Cylindrical wheels without proper tires.
- Primitive headlights and taillights.
- Identical-looking vehicles with different colors.
- Low-poly appearance.

Do not interpret stylized realism as permission to simplify vehicle geometry excessively.

## 2. Passenger Cars

Passenger cars are the highest priority.

Create believable automotive body geometry.

Important details:

### Bodywork
- Properly curved body panels.
- Rounded hood and trunk.
- Realistic roof shape.
- Properly shaped wheel arches.
- Front and rear bumpers integrated into the body.
- Side skirts where appropriate.
- Realistic doors and panel transitions.
- Proper front and rear proportions.
- Side mirrors.
- Door handles.
- Fuel filler caps.

The vehicle silhouette must be recognizable from multiple viewing angles.

### Windows
- Properly shaped windshield.
- Rear window.
- Side windows.
- Window frames.
- Appropriate glass transparency and reflections.
- Visible interior silhouettes where practical.

Windows must follow the actual body geometry rather than being simple flat rectangles attached to the vehicle.

### Wheels and Tires
Create convincing wheels:
- Proper tire width and profile.
- Rounded tire geometry.
- Visible rims.
- Lug details where practical.
- Correct wheel proportions.
- Appropriate tire materials.
- Realistic wheel positioning inside the wheel arches.

Wheels must remain correctly aligned with the vehicle during steering and suspension movement.

### Lights
Create detailed:
- Headlights.
- Daytime running lights.
- Turn indicators.
- Brake lights.
- Rear lights.
- Reverse lights.

Use emissive materials where appropriate.

Lighting must remain consistent with the existing vehicle lighting system.

## 3. Other Vehicle Categories

Apply the same quality standards to every vehicle category.

### Taxis and Passenger Cars
Provide substantial model variation.

Include different:
- Body styles.
- Vehicle sizes.
- Rooflines.
- Front designs.
- Rear designs.
- Wheel designs.
- Colors.

Taxis should have appropriate taxi signs and markings.

### Vans
Include realistic cargo vans and passenger vans.

### Trucks
Include believable truck cabins, chassis, wheels, cargo areas and trailers where supported.

### Buses
Include realistic bus proportions, windows, doors, lights and interior silhouettes.

### Motorcycles
Include:
- Frame.
- Fuel tank.
- Engine.
- Exhaust.
- Wheels.
- Suspension.
- Handlebars.
- Mirrors.
- Headlights.
- Seat.

### Bicycles
Include:
- Frame geometry.
- Wheels and spokes.
- Handlebars.
- Saddle.
- Pedals.
- Chain.
- Fork.

All categories must retain their existing gameplay identities.

## 4. Vehicle Materials

Materials are essential to the result.

Use physically believable material properties.

Examples:

Car paint:
- Metallic paint where appropriate.
- Clearcoat-like reflections.
- Controlled roughness.
- Subtle surface variation.

Glass:
- Appropriate transparency.
- Reflections.
- Slight tint variation.

Rubber:
- Matte appearance.
- Realistic tire sidewalls.

Metal:
- Different finishes for chrome, painted metal and untreated metal.

Plastic:
- Bumpers, trim and dashboards should have appropriate material characteristics.

Lights:
- Separate glass and emissive components.

Avoid making every surface equally shiny.

## 5. Vehicle Interiors

Where practical, introduce visible vehicle interiors.

At minimum:
- Dashboard silhouette.
- Front seats.
- Rear seats.
- Steering wheel.
- Interior surfaces.

Interiors should be visible through windows at appropriate camera distances.

Do not spend excessive resources on details that cannot be seen during gameplay.

## 6. Vehicle Variety and Finnish Context

Vehicles should represent believable traffic in a modern Finnish city.

Include appropriate vehicle types:
- Small European hatchbacks.
- Sedans.
- Station wagons.
- SUVs.
- Electric vehicles.
- Commercial vans.
- Delivery vehicles.
- Heavy trucks.
- City buses.
- Motorcycles.

Avoid making all vehicles look like variations of one generic model.

Introduce visual variation through different body designs, colors, wheel designs and vehicle details.

Preserve the existing traffic composition and seasonal behavior.

## 7. Geometry and Model Architecture

First audit how current vehicle models are constructed.

Determine whether they are:
- Procedurally generated meshes.
- Collections of primitive meshes.
- Imported 3D assets.
- A combination of these.

Choose the best architecture for long-term visual quality.

Prefer properly modeled reusable vehicle assets over increasingly complicated collections of primitive geometry.

Consider Blender-authored models exported as glTF for Godot.

Use reusable components where appropriate:
- Wheels.
- Tires.
- Mirrors.
- Lights.
- Interior components.
- Shared materials.

Different vehicle models should have genuinely different geometry and silhouettes.

Do not simply change the dimensions and colors of the same generic car model.

## 8. Performance

The game simulates substantial amounts of traffic.

Visual improvements must not compromise performance.

Implement:
- Multiple LOD levels.
- Distance-based detail reduction.
- Shared materials.
- Shared mesh resources.
- GPU instancing where appropriate.
- Efficient wheel and light components.
- Visibility-based rendering.
- Appropriate interior detail reduction.

Close vehicles should look excellent.

Distant vehicles should retain recognizable silhouettes without unnecessary geometry.

Do not introduce arbitrary global vehicle count limits.

Preserve existing visibility management and spatial culling.

Do not render vehicles outside the relevant visible area.

## 9. Preserve Existing Simulation

This is strictly a visual upgrade.

Python remains authoritative for:
- Vehicle movement.
- Physics.
- Collision detection.
- Vehicle dimensions.
- Vehicle positioning.
- Traffic rules.
- Gameplay logic.

Godot remains responsible for rendering and visual presentation.

Do not move vehicle simulation responsibilities into Godot.

Preserve:
- Vehicle IDs.
- Vehicle positions.
- Vehicle orientations.
- Wheel steering synchronization.
- Existing animations.
- Lighting states.
- Vehicle spawning and despawning.
- Collision geometry compatibility.

If visual dimensions differ from simulation dimensions, keep the two systems explicitly synchronized.

Do not let improved visual geometry accidentally change collision behavior.

## 10. Controlled Visual Testing

Visual validation is mandatory.

Create a controlled test scene containing representative examples of every vehicle category.

Do not randomly spawn vehicles and assume that the resulting scene provides reliable validation.

Test:
- Front view.
- Rear view.
- Side view.
- Three-quarter view.
- Close-up view.
- Normal gameplay camera distance.
- Daylight.
- Evening.
- Night.
- Rain or other available weather conditions.

Pay special attention to reflections and lighting.

Capture before-and-after screenshots.

Evaluate the vehicles as complete models, not just individual components.

## 11. Implementation Phases

Implement incrementally.

Recommended order:

1. Passenger car body geometry.
2. Wheels, tires and wheel arches.
3. Windows, lights and exterior details.
4. Materials and reflections.
5. Vehicle interiors.
6. Vehicle model variation.
7. Vans and commercial vehicles.
8. Trucks and buses.
9. Motorcycles.
10. Bicycles.
11. LOD and performance optimization.
12. Final visual validation.

Passenger cars must reach the target quality before proceeding to the remaining categories.

Make atomic commits for logically complete changes.

Do not rewrite unrelated rendering or simulation systems.

## Definition of Done

Every vehicle category must have a visually convincing, high-quality 3D appearance.

Passenger cars must no longer resemble primitive rectangular boxes.

Vehicles must have believable proportions, curved bodywork, detailed wheels, appropriate materials, realistic lighting and recognizable silhouettes.

The result must fit the existing stylized-realistic human and animal characters and the overall visual direction of Road Rage Taxi.