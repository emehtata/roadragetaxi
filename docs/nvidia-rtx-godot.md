# NVIDIA RTX Godot: experimental adoption analysis

Research date: 1 November 2026. This is an implementation proposal, not a
claim that the fork has been built or the game tested on it.

## Recommendation

Introduce an explicit Windows experimental engine launch, then validate
Forward+ raster rendering before enabling path tracing in a selected 3D view.
Use the existing first-person home interior as the first path tracing trial:
it already has shaded meshes, a dedicated 3D world and an Environment. Treat
outdoor path tracing as a later rendering project because the driving view
combines a 2D map with transparent 3D building and shadow textures.

A successful engine launch alone does not establish path tracing support.
The adoption gates are: compatible engine, working Vulkan Forward+, working
Streamline features, correctly configured per-view Environment, and measured
visual benefit at an acceptable cost.

## What NVIDIA actually provides

The [linked website](https://nvidia-rtx.github.io/godot/) currently repeats
Godot's general README. Its upstream download links do not supply an RTX
build. Use NVIDIA's source repository and inspect the RTX branch explicitly.

The [branch API](https://api.github.com/repos/NVIDIA-RTX/godot/branches/nvidia-pt-dlss)
resolved `nvidia-pt-dlss` to
`135dff3887a3d2ccf45cafbd9bdffa7b718e1e76`, dated 24 July 2026. Pin that
revision for an initial reproducible evaluation. Recheck this information
before implementation; it describes the inspected revision, not every fork
version. The [official releases API](https://api.github.com/repos/NVIDIA-RTX/godot/releases)
returned no releases at inspection time. Community binaries are a separate
supply and maintenance decision.

| Finding at the inspected revision | Consequence for this game |
| --- | --- |
| [version.py](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/version.py) reports 4.8-dev | This is a development-engine compatibility change from the game's pinned 4.7.2. Test scripts, shaders and imports. |
| [SConstruct](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/SConstruct) defaults `use_streamline` to true but disables it outside Windows | Start with native Windows. Linux path tracing without Streamline is a separate experiment, not equivalent DLSS support. |
| [RenderingDevice reference](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/doc/classes/RenderingDevice.xml) documents ray tracing pipeline support as Vulkan-only | Select `forward_plus` and `vulkan` explicitly. Streamline's D3D12 code does not prove D3D12 path tracing works. |
| [Environment reference](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/doc/classes/Environment.xml) exposes `pathtracing_enabled` and a DLSS Ray Reconstruction denoiser | Path tracing is enabled per Environment, independently of launching the engine. The listed denoisers are None and DLSS Ray Reconstruction. |
| [Viewport reference](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/doc/classes/Viewport.xml) adds `SCALING_3D_MODE_DLSS` | DLSS scales a viewport's 3D buffer. It will not accelerate all the game's 2D drawing or the Python simulation. |
| [Streamline headers](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/thirdparty/streamline/include/sl_version.h) specify SDK 2.10.0 | Begin with matching runtime files and record their versions. Avoid assuming the newest SDK is interchangeable. |

The path tracer requires ray tracing hardware. DLSS Ray Reconstruction
specifically requires an NVIDIA RTX GPU according to the fork's Environment
reference. Query actual feature capabilities; GPU branding alone does not
establish usable DLSS, Frame Generation or Reflex support. Do not publish a
minimum driver or VRAM requirement until a build and hardware matrix verifies
it. An RTX 5060 with 8 GB is a useful local trial target, not an established
minimum specification.

## Fit with the current game

The relevant integration points are:

| File | Current behavior | Proposed responsibility |
| --- | --- | --- |
| [Makefile](../Makefile) | Pins 4.7.2; WSL `run` delegates to native Windows; other run targets use `GODOT` | Add an explicit experimental target and a separate fork executable variable. |
| [tools/run-windows.ps1](../tools/run-windows.ps1) | Accepts `-Godot`, chooses Windows Python, prepares osmium and launches the project | Select and validate the experimental executable and pass engine arguments before `--`. |
| [godot/project.godot](../godot/project.godot) | Uses `gl_compatibility` | Override renderer and driver at process launch. |
| [godot/startup.gd](../godot/startup.gd) | Owns menus and saved launch preferences | Later expose a restart-based experiment choice if the command-line trial succeeds. |
| [godot/graphics_settings.gd](../godot/graphics_settings.gd) | Reads eight boolean graphics preferences | Keep engine selection distinct from live effect toggles; add validated RTX view options only when needed. |
| [godot/home_first_person.gd](../godot/home_first_person.gd) | Creates an isolated SubViewport, WorldEnvironment and directional light | First candidate for guarded path tracing and per-viewport DLSS configuration. |
| [godot/buildings_3d.gd](../godot/buildings_3d.gd) | Composites transparent buildings and a separate multiplied ground-shadow texture | Requires a separate visual design and compatibility trial before outdoor path tracing. |
| [.github/workflows/windows-release.yml](../.github/workflows/windows-release.yml) | Downloads upstream editor/templates and packages one Windows client | A later RTX distribution needs templates built from the pinned fork and its own runtime manifest. |

The outdoor buildings use unshaded materials and
[building_snow.gdshader](../godot/building_snow.gdshader), with much of their
lighting encoded in vertex colors and shader output. Their sun and shadow
caster copies use a separate layer and a separate shadow viewport. Roads,
vehicles and pedestrians are predominantly CanvasItem content outside that
3D world. Path tracing cannot infer 3D geometry or lighting interactions for
those 2D layers.

The resulting risks are specific: transparent-background alpha may composite
differently, denoising can leave trails around roofs, cull masks may not have
the expected ray visibility behavior, and the existing multiplied shadow pass
may double-darken a new lighting result. Shaded outdoor materials also need
to avoid applying the existing baked lighting twice. These are evaluation
questions, not confirmed fork defects. Do not enable path tracing globally
on the building or shadow Environment to see whether it happens to work.

The home interior has shaded StandardMaterial3D surfaces and a mostly opaque
full-screen 3D view, making it a smaller trial. It still needs deliberate
lighting: its current ambient fill and directional light may not reproduce
the desired interior appearance under path tracing, and missing ceilings or
exterior geometry can affect light leakage. Use a selected room and a
controlled light first.

Python remains authoritative for the existing simulation. Engine selection
must not change the protocol, map layer semantics, traffic decisions or
server timing. GPU rendering work also cannot remove CPU costs from chunk
construction, GDScript drawing or simulation.

## Prepare a reproducible engine build

Use a separate engine checkout and a separate game worktree for evaluation.
This isolates development-engine imports and editor rewrites in `godot/.godot`
from the normal checkout. Back up the game's Godot settings and save files
before trying the development engine; worktrees share `user://` unless given
separate user-data configuration. An experimental application name or custom
user directory can be configured in that worktree if persistent isolation is
needed. Keep map/server assets at their existing relative locations.

On a Windows machine with the toolchain described in Godot's
[Windows compilation guide](https://docs.godotengine.org/en/latest/engine_details/development/compiling/compiling_for_windows.html),
install compatible MSVC C++ tools, the Windows SDK, Python and SCons. Example
PowerShell commands for the inspected revision:

```powershell
git clone --branch nvidia-pt-dlss --single-branch https://github.com/NVIDIA-RTX/godot.git C:\Godot\nvidia-godot
Set-Location C:\Godot\nvidia-godot
git checkout --detach 135dff3887a3d2ccf45cafbd9bdffa7b718e1e76
scons platform=windows target=editor arch=x86_64 use_streamline=yes
Get-ChildItem .\bin\*console.exe
```

These are proposed build commands, not a tested build transcript. Resolve
build prerequisites against the pinned source and its build output. Record
the compiler, SCons version, engine SHA and resulting binary filename; use
the actual console executable emitted by the build rather than assuming an
upstream release filename.

Obtain the matching Streamline SDK from
[NVIDIA's Streamline repository](https://github.com/NVIDIA-RTX/Streamline).
Use the SDK's documented runtime deployment files for the selected features,
including the interposer, feature plugins and required NGX DLLs, beside the
engine executable. Preserve the SDK's runtime layout and notices; copying
headers does not install the runtime. The fork explicitly loads
`sl.interposer.dll` through Windows LoadLibrary in
[streamline_context.cpp](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/drivers/streamline/streamline_context.cpp).
Use release runtime files for any distributed package. Record hashes and
versions of the deployed files, not just the engine executable.

One reproducibility detail needs attention: that same source initializes
Streamline with `eAllowOTA | eLoadDownloadedPlugins` and a hard-coded
application ID. Pinning DLLs alone therefore does not guarantee an unchanged
runtime. Record loaded plugin versions during testing; review the OTA policy
and application identity before distribution.

## Try the engine before implementing launch support

Use the isolated game worktree and native Windows rendering. From its root,
replace `$rtxGodot` with the actual compiled console executable:

```powershell
$rtxGodot = 'C:\Godot\nvidia-godot\bin\ACTUAL_CONSOLE_EXECUTABLE.exe'
& $rtxGodot --version
& $rtxGodot --headless --path .\godot --editor --import --quit
& $rtxGodot --path .\godot --rendering-method forward_plus --rendering-driver vulkan
```

The last invocation opens the existing game launcher with Forward+ raster
rendering. It does not enable path tracing. Use the documented Windows Python
environment from [README](../README.md#run-from-source) so the launcher can
start its server. The existing PowerShell helper's `-Godot` parameter already
supports a different executable, but it has no renderer/driver parameters:
passing only `-Godot` leaves this project on Compatibility.

Headless import detects script/resource problems. It cannot demonstrate RT
capabilities, successful DLSS initialization, visible rendering or performance.
Under WSL use the native Windows executable and Windows Python environment;
do not use Linux Mesa/software results to characterize Windows RTX performance.

## Proposed experimental launch implementation

The smallest useful first implementation is `make run-rtx` with a separate
`WINDOWS_RTX_GODOT` executable path and an `-ExperimentalRtx` switch on the
PowerShell helper. These names are proposals and do not exist yet. The helper
should construct an engine-argument array and launch approximately:

```text
<fork-console.exe> --path <game>/godot --rendering-method forward_plus --rendering-driver vulkan -- <existing game arguments>
```

The existing `--log-level` and `--osm-source` options belong after `--`;
renderer/driver options belong before it. Preserve correct quoting for paths
with spaces and existing Windows Python selection. An explicit CLI renderer
and driver override is sufficient: a second project file or generated project
copy is unnecessary for renderer selection. Use the isolated worktree during
the initial evaluation to protect imports.

Validate executable existence and report its version at launch. Do not point
`fetch-godot` at the fork: its download URL and filename convention are for
upstream releases. Add a fork-revision marker or build manifest because the
version string `4.8.dev` does not uniquely identify NVIDIA's features. Keep
normal headless checks pinned to the established engine; add a fork import
check as a separate compatibility check.

A failed experiment should print the cause and the standard launch command,
return a nonzero status, and leave a useful log. Avoid automatic relaunch loops
or silently substituting the standard engine. Log the actual renderer and GPU
because an engine fallback can otherwise look like a successful RTX launch.

An in-game experimental selector is a later step. Engine and renderer
selection happen before the menu exists, so that choice needs an external
launcher or a controlled restart. For packaged games the selected engine is
part of the exported executable: a setting cannot transform an upstream
export into the NVIDIA fork.

## Enable path tracing in a bounded 3D trial

Add a small optional client helper used first by `home_first_person.gd`.
Keep fork-only APIs behind runtime discovery so standard Godot still parses
and runs the project. Avoid direct references to unknown `Streamline` classes
or fork-only enum symbols in scripts parsed by upstream Godot.

The helper should verify the selected rendering method and Vulkan device,
check that Environment has `set_pathtracing_enabled`, and query the rendering
device for ray tracing pipeline support. Obtain `Streamline` dynamically via
`Engine.has_singleton` / `Engine.get_singleton`, and query `get_capability`
using constants discovered through ClassDB. The fork's
[Streamline reference](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/doc/classes/Streamline.xml)
exposes separate capabilities for DLSS, Ray Reconstruction, Frame Generation
and Reflex. Fail closed for missing APIs or capabilities and explain the
unavailable feature.

Configure the Environment actually assigned to the interior's WorldEnvironment.
Set path tracing through guarded `Object.call`/`set` operations. Initial values
for a measured trial are one sample per pixel, two bounces and DLSS Ray
Reconstruction, when available. The implementation clamps bounces to 1–8 in
[environment.cpp](https://github.com/NVIDIA-RTX/godot/blob/135dff3887a3d2ccf45cafbd9bdffa7b718e1e76/scene/resources/environment.cpp);
its XML description of zero bounces should not be treated as a supported
setting at this revision.

Configure DLSS on the interior SubViewport, not only the root window. Discover
`SCALING_3D_MODE_DLSS` dynamically; start with scale 1.0 for image comparison,
then evaluate the documented 0.66 Quality scale. Confirm which reconstruction
path is actually active. The root window's 2D HUD and map compositing do not
become DLSS 3D content by changing a scaling option there.

Leave Frame Generation for a separate evaluation. It requires its own
capability checks and presentation integration; a generated frame rate does
not measure simulation throughput or input responsiveness. Reset view options
when exiting the interior, and verify repeated entry/exit releases resources.

## Acceptance and performance evidence

Implementation is ready for an experimental launch only after these checks:

1. Upstream launch still works; both engines import the project's scripts and
   resources. Missing executable, DLLs, RT support or DLSS capabilities produce
   a specific explanation. The experimental startup log identifies the pinned
   build, native GPU, Vulkan driver, rendering method and requested/active features.
2. Forward+ raster displays the launcher, driving map, night/weather effects,
   buildings, shadows and home view correctly. Inspect alpha edges, map alignment,
   color space, glass, custom shaders, text and the multiplied shadow pass.
3. A controlled room visibly demonstrates path traced indirect lighting or
   reflection. Moving and turning reveal no unacceptable ghosting or trails.
   Capture and inspect screenshots, as required by AGENTS.md for UI/Godot changes.
4. Compare normal Compatibility, fork Forward+ raster, path tracing at native
   scale, and path tracing with DLSS Quality at the same resolution and scene.
   Keep frame generation disabled. Warm shader caches separately from cold-start
   measurements. Record median and high-percentile frame times, VRAM, chunk-load
   stalls, input behavior and shader compilation pauses with matching game state.
5. Repeat interior transitions, resize and zoom; load/unload streamed outdoor
   chunks; then launch upstream again. Check saved settings and server state
   remain usable. Use the project's existing Godot checks and sample selftest
   for compatibility, while recognizing that headless checks cannot validate RT.

Use the existing `--bench` reporting for available client metrics, alongside
native GPU tools for GPU timing and VRAM. Set the acceptable frame-time and
memory budget before deciding to expand the experiment. This document makes
no speedup claim; 2D or CPU-bound scenes may become slower on Forward+.

## Distribution and maintenance gate

If the trial succeeds, build Windows export templates (`target=template_debug`
and `target=template_release`, `arch=x86_64`, `use_streamline=yes`) from the same
pinned source. Configure explicit custom templates for an experimental export
preset; upstream 4.7.2 templates do not contain the fork's renderer. Validate
the exported executable on a clean machine, including its Python server,
relative asset paths and Streamline runtime discovery.

Package the experiment as a clearly identified optional artifact with an
engine/runtime version manifest. Extend the release workflow and
[license inventory](../tools/license_inventory.json), regenerate engine notices
with [godot_licenses.gd](../tools/godot_licenses.gd), and inventory the runtime
DLLs and their actual redistribution terms. The engine's MIT license does not
by itself describe all NVIDIA runtime redistribution obligations. Review the
chosen SDK's supplied license and deployment guidance before shipping.

Keep upgrades deliberate: new engine SHA, matching runtime review, import and
render checks, screenshots and the same performance scenes. A full outdoor
conversion would require additional 3D ground, objects, materials and lights
while preserving map-layer separation and bounded chunk work. Scope that as
its own rendering feature after the home-interior trial establishes value.
