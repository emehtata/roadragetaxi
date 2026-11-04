# Task: Upgrade Human and Animal Character Visual Quality

The game now uses a proper 3D rendering environment in Godot. However, human and animal characters currently look overly angular, primitive and artificial.

Your task is to significantly improve the visual quality of all human and animal characters in the game.

The target is **high-quality stylized realism (semi-realistic 3D)**.

Characters should look almost natural and believable, with slightly cartoon-like artistic exaggeration. They should fit naturally into the existing 3D city environment.

This is a visual quality upgrade, not a simulation rewrite.

## 1. Visual Direction

Target characteristics:

- Believable human and animal anatomy.
- Smooth, natural body shapes.
- Properly rounded geometry instead of visibly angular primitive shapes.
- Natural body proportions.
- Detailed but not photorealistic faces.
- Subtle artistic exaggeration.
- Smooth shading and carefully constructed materials.
- Natural-looking skin, fur, clothing and other surfaces.
- Visually recognizable silhouettes.
- High-quality appearance at normal gameplay camera distances.

Avoid:
- Minecraft-like geometry.
- Low-poly characters.
- Primitive capsule-based human bodies.
- Oversized cartoon heads.
- Childish proportions.
- Plastic-looking skin.
- Excessively shiny materials.
- Unnecessarily complicated geometry.

The characters must look like inhabitants of a believable modern Finnish city.

## 2. Human Characters

Upgrade all human character models.

### Anatomy
- Use anatomically believable body proportions.
- Improve head, neck, shoulders, torso, arms, hands, legs and feet.
- Introduce smooth transitions between body parts.
- Avoid visible gaps between body components.
- Ensure joints look natural.

### Faces
- Introduce recognizable facial geometry.
- Add eyes, eyelids, eyebrows, nose, mouth and ears.
- Support different facial appearances.
- Avoid simple flat facial textures.
- Provide subtle facial expressions where practical.

### Clothing
Create believable clothing geometry and materials.

Support different clothing categories:
- Casual everyday clothing.
- Winter jackets.
- Hoodies and sweaters.
- T-shirts.
- Trousers and jeans.
- Shorts.
- Skirts and dresses.
- Work clothing.
- High-visibility clothing.
- Seasonal Finnish clothing.

Clothing should have visible shape, folds and material variation.

### Character Variety

NPCs should not look like clones.

Introduce procedural visual variation:
- Different body builds.
- Different heights.
- Different hairstyles.
- Different clothing combinations.
- Different skin tones.
- Different facial features.
- Different age appearances.

All variation must remain within believable human proportions.

## 3. Animal Characters

Apply the same visual quality standards to all existing animal models.

Animals should have recognizable anatomy and natural proportions.

Pay particular attention to:
- Smooth body silhouettes.
- Proper head and muzzle shapes.
- Natural legs and joints.
- Ears and tails.
- Eyes and facial details.
- Fur appearance.
- Species-specific proportions.

Fur should be represented using efficient materials, textures or geometry techniques appropriate for the game's rendering budget.

Do not simply replace angular animals with higher-polygon versions of the same primitive shapes. Reconstruct their visual appearance properly.

Preserve species-specific behavior and animations.

## 4. Materials and Shading

Use appropriate materials for different surfaces.

Examples:
- Skin: subtle roughness and natural color variation.
- Clothing: fabric-like roughness.
- Leather: slightly different surface response.
- Fur: soft, non-plastic appearance.
- Eyes: realistic reflections without excessive gloss.
- Shoes: appropriate material differentiation.

Use smooth shading where appropriate.

Pay attention to normal generation and geometry smoothing.

Avoid excessive metallic or glossy reflections on organic surfaces.

## 5. Animation Compatibility

Existing animation and movement systems must continue working.

Improve visual transitions between:
- Walking.
- Running.
- Standing.
- Turning.
- Sitting, where applicable.
- Animal movement.

Ensure that improved geometry does not introduce joint deformation problems.

If the current models do not support proper skeletal animation, evaluate introducing a reusable skeletal character architecture.

Do not break existing NPC movement or simulation logic.

## 6. Performance Requirements

This is a large NPC simulation game.

Visual improvements must not compromise simulation or rendering performance.

Requirements:

- Reuse meshes and materials wherever possible.
- Use GPU instancing where appropriate.
- Use level-of-detail (LOD) models.
- Use simpler geometry for distant characters.
- Avoid unnecessary real-time material complexity.
- Avoid excessive draw calls.
- Avoid generating unique resources for every NPC.
- Keep animation costs under control.
- Ensure off-screen characters are not unnecessarily rendered or animated.

Use the existing visibility and distance management systems.

Do not introduce arbitrary global NPC visibility limits.

## 7. Technical Architecture

Before making changes:

1. Audit the current human and animal model implementations.
2. Identify all places where character geometry is created.
3. Identify how models are instantiated and reused.
4. Inspect the existing animation system.
5. Identify all dependencies between visual models and server-side simulation.
6. Determine which improvements can be implemented without changing gameplay logic.

Keep the architecture clean.

Where practical, create reusable character components:
- Human base model.
- Human head variations.
- Clothing components.
- Animal base models.
- Species-specific animal components.
- Shared materials.
- LOD variants.

Godot handles rendering and visual presentation. The Python server remains authoritative for simulation, movement and gameplay rules.

Do not move simulation responsibilities into the Godot client.

## 8. Testing and Visual Validation

Visual validation is mandatory.

Do not consider the task complete merely because the code runs.

Create a controlled visual test environment with:
- Several human NPCs.
- Different body types.
- Different clothing combinations.
- Multiple animal species.
- Close-up character views.
- Normal gameplay camera distance.
- Different lighting conditions.

Place characters deliberately in suitable locations.

Do not randomly spawn test characters and assume the resulting scene is representative.

Test:
- Daylight.
- Evening lighting.
- Night lighting.
- Different camera distances.
- Character movement.
- Animation transitions.

Capture screenshots before and after the changes.

Compare the results.

Verify that:
- Characters no longer look primitive or excessively angular.
- Human anatomy is believable.
- Animals are recognizable and naturally proportioned.
- Materials look appropriate.
- Characters fit the existing environment.
- Performance remains acceptable.

## 9. Implementation Strategy

Implement this incrementally.

Suggested phases:

1. Human base model quality.
2. Human faces and clothing.
3. Human visual variation.
4. Animal model quality.
5. Animal species-specific details.
6. Materials and shading.
7. Animation refinement.
8. LOD and performance optimization.
9. Final visual validation.

Make atomic commits for logically complete improvements.

Do not rewrite unrelated rendering or simulation systems.

Do not sacrifice visual quality simply to finish faster.

## Definition of Done

The upgrade is complete when human and animal characters have a consistent, high-quality stylized-realistic appearance.

They should look like professionally designed 3D game characters rather than collections of primitive geometric shapes.

The result must remain compatible with the existing Python simulation and Godot rendering architecture.