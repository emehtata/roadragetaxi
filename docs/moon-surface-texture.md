# Moon surface texture

The sky's Moon disc samples `godot/assets/moon/2k_moon.jpg` as an
equirectangular albedo map. East-west is oriented as seen from Earth, and the
lunar north pole is projected into the observer's sky using the J2000 celestial
basis. The pole uses the IAU mean direction from [JPL D-32296](https://ssd.jpl.nasa.gov/doc/lunar_cmd_2005_jpl_d32296.pdf); periodic pole terms and optical libration are not modelled. The existing shader still controls the apparent disc, lunar phase, cloud occlusion and stars; the texture only supplies the surface's visible maria and crater detail.

The lit albedo stays below display clipping in Forward+; the earlier HDR
brightness washed the map out to white. The native `moon_phase.gd` render check
samples only the central lunar interior and rejects clipped white pixels.
`oulu_gibbous_moon` also requires contrast from the confidently lit interior,
separately from its existing spherical phase and curved-terminator checks.
The named scenario passed on Windows Godot with Forward+ / Vulkan (NVIDIA RTX
5060): 615 lit-interior samples measured 0.329 contrast, no clipped samples,
and 23 curved-limb samples at 92.7% illumination. Its readiness-passed
screenshot was visually inspected at the scenario's normal resolution.

## Source and licence

- Creator/attribution: Solar System Scope, [Solar Textures](https://www.solarsystemscope.com/textures/).
- Asset: `2k_moon.jpg`, downloaded from
  `https://spaceengine.solarsystemscope.com/textures/download/2k_moon.jpg`.
- Licence: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
- The full licence text, source metadata, image hash and notice are retained in
  `godot/assets/moon/`.
- In-game attribution is shown in Finnish, English and German under Credits →
  Textures.

Solar System Scope says the planet textures are based on NASA imagery, with
slightly saturated colors and unmapped areas filled with fictional terrain.
The texture is distributed unchanged and the project makes no NASA endorsement
claim.
