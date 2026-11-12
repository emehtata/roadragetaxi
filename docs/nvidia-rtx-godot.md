# NVIDIA RTX Godot: experimental adoption analysis

Research and project status reviewed: 1 November 2026. The experimental
launch and runtime capability checks are implemented. Scene acceptance and
performance evidence are recorded separately from successful configuration.

For the ordered game-scene conversion prerequisites, see
[Outdoor scene prerequisites before enabling RTX](rtx-scene-readiness.md).

## Recommendation

Proceed with the controlled outdoor trial in
[scene readiness Step 7](rtx-scene-readiness.md#step-7-prove-readiness-and-enable-a-controlled-rtx-trial).
The preparation work in Steps 1–6 is implemented and has been rendered under
native Windows Forward+/Vulkan. The remaining exclusions and evidence are
recorded in that plan. The first-person home interior is another test view,
not a prerequisite for the outdoor trial.

## Implementation status

The opt-in `--outdoor-3d` path now renders chunk-owned ground, roads, wet
surfaces, buildings, bridges, roadside props, vehicle kinds, people and larger
animals in a shared World3D. Generated meshes carry normals; shaded materials
separate paint, glass, rubber and emissive parts. Real scene lights replace
the old lighting and multiplied shadow composition on this path. The standard
Compatibility presentation remains the default.

Experimental RTX integration adds `make run-rtx` and `--rtx`, which selects
that outdoor scene and requires the NVIDIA engine, Vulkan Forward+, ray tracing
pipeline support, DLSS and DLSS Ray Reconstruction. Fork-only classes,
constants and methods are discovered at runtime by
[rtx_trial.gd](../godot/rtx_trial.gd); upstream Godot can still load the project.
Unavailable requirements produce an explanation and a nonzero exit before
starting a session. The trial configures the outdoor SubViewport and, when
entered, the separate home-interior SubViewport. It uses one sample per pixel,
two bounces, Ray Reconstruction, native scale or DLSS Quality, and no Frame
Generation. `RTX_TRIAL` log records identify the engine, GPU, renderer, driver
and configured view. The trial disables asynchronous path-tracing shader
compilation: the initial
probe otherwise captured missing custom-material geometry even after waiting.
Cold first frames can therefore pause while materials compile. Configuration
is not proof that every shader or scene feature renders correctly; see the
[trial results](rtx-trial-2026-11-01.md) for captures and remaining gates.

## What NVIDIA actually provides

The [linked website](https://nvidia-rtx.github.io/godot/) currently repeats
Godot's general README. Its upstream download links do not supply an RTX
build. Use NVIDIA's source repository and inspect the RTX branch explicitly.

The [branch API](https://api.github.com/repos/NVIDIA-RTX/godot/branches/nvidia-pt-dlss-dev)
resolved `nvidia-pt-dlss-dev` to
`382d9d6bf0274af34b85d3cbcd98981de41cbd62`, dated 1 November 2026. Pin that
revision for this reproducible evaluation. At 20:37 UTC the branch had been
force-updated to `6a7a8406875c92b033c929bd284536a5c7d71209`. A recursive
blob comparison found eight changed files: include cleanup and test guards,
with no rendering algorithm changes. The recorded binary and screenshots
remain pinned to `382d9d6`; `6a7a840` was inspected but not built. Do not confuse
a moving branch name with the tested build identity. Recheck the branch before
upgrading; these findings describe the inspected revision, not every fork
version. The older `nvidia-pt-dlss` branch at `135dff3` failed the first
street trial: it did not preserve UV2/CUSTOM0 material data and rejected the
puddle shader's discard. Use the development branch pinned above, which adds
vertex capture, UV2 and improved alpha handling. It declares CUSTOM0 but does
not populate it from mesh data; the trial therefore also requires the small
[custom0.patch](../tools/rtx/custom0.patch). This restores the FLOAT4 CUSTOM0
window parameters used by our building material, and adds the
`rrt_rtx_custom0` engine feature checked at startup. It does not implement
other custom formats or CUSTOM1–3. The road material also uses an explicit camera footprint instead of `dFdx`/`dFdy`,
which cannot execute in ray hit shaders.

The [official releases API](https://api.github.com/repos/NVIDIA-RTX/godot/releases)
returned no releases at inspection time. Community binaries are a separate
supply and maintenance decision.

| Finding at the inspected revision | Consequence for this game |
| --- | --- |
| [version.py](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/version.py) reports 4.8-dev | This is a development-engine compatibility change from the game's pinned 4.7.2. Test scripts, shaders and imports. |
| [SConstruct](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/SConstruct) defaults `use_streamline` to true but disables it outside Windows | Start with native Windows. Linux path tracing without Streamline is a separate experiment, not equivalent DLSS support. |
| [RenderingDevice reference](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/doc/classes/RenderingDevice.xml) documents ray tracing pipeline support as Vulkan-only | Select `forward_plus` and `vulkan` explicitly. Streamline's D3D12 code does not prove D3D12 path tracing works. |
| [Environment reference](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/doc/classes/Environment.xml) exposes `pathtracing_enabled` and a DLSS Ray Reconstruction denoiser | Path tracing is enabled per Environment, independently of launching the engine. The listed denoisers are None and DLSS Ray Reconstruction. |
| [Viewport reference](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/doc/classes/Viewport.xml) adds `SCALING_3D_MODE_DLSS` | DLSS scales a viewport's 3D buffer. It will not accelerate all the game's 2D drawing or the Python simulation. |
| [Streamline headers](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/thirdparty/streamline/include/sl_version.h) specify SDK 2.10.0 | Begin with matching runtime files and record their versions. Avoid assuming the newest SDK is interchangeable. |

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
| [Makefile](../Makefile) | Pins 4.7.2 for standard runs; `run-rtx` selects `WINDOWS_RTX_GODOT` | Keep the experimental engine explicit and record the selected build. |
| [tools/run-windows.ps1](../tools/run-windows.ps1) | Accepts `-Godot`, `-ExperimentalRtx`, and `-RtxQuality`; chooses Windows Python and prepares osmium | Pass Vulkan/Forward+ before `--` and RTX game flags after it. |
| [godot/project.godot](../godot/project.godot) | Uses `gl_compatibility` | Override renderer and driver at process launch. |
| [godot/startup.gd](../godot/startup.gd) | Owns menus and saved launch preferences | Later expose a restart-based experiment choice if the command-line trial succeeds. |
| [godot/graphics_settings.gd](../godot/graphics_settings.gd) | Reads eight boolean graphics preferences | Keep engine selection distinct from live effect toggles; add validated RTX view options only when needed. |
| [godot/home_first_person.gd](../godot/home_first_person.gd) | Creates an isolated SubViewport, WorldEnvironment and directional light | Applies the same guarded RTX configuration to its own view during the trial. |
| [godot/buildings_3d.gd](../godot/buildings_3d.gd) | Outdoor mode has an opaque shared scene, shaded materials and real lights | Applies RTX to the outdoor camera Environment and its SubViewport. |
| [godot/entity_layer.gd](../godot/entity_layer.gd) | Submits all vehicle categories and nearby people to the outdoor 3D layer | Verify moving meshes, lamp states and temporal reconstruction in the trial. |
| [.github/workflows/windows-release.yml](../.github/workflows/windows-release.yml) | Downloads upstream editor/templates and packages one Windows client | A later RTX distribution needs templates built from the pinned fork and its own runtime manifest. |

The legacy transparent building view still exists for the standard game.
The RTX trial uses the prepared opaque outdoor mode instead. Its outstanding
fork-specific questions are custom shader compatibility, transparency and
particles, small 2D overlays, dense foliage, off-screen reflection coverage,
and temporal reconstruction of pooled moving meshes. Check the readiness
plan's exclusions and compare the rendered results rather than inferring
support from a successful engine launch.

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
git clone --branch nvidia-pt-dlss-dev --single-branch https://github.com/NVIDIA-RTX/godot.git C:\Godot\nvidia-godot
Set-Location C:\Godot\nvidia-godot
git checkout --detach 382d9d6bf0274af34b85d3cbcd98981de41cbd62
git apply C:\path\to\roadragetaxi\tools\rtx\custom0.patch
scons platform=windows target=editor arch=x86_64 use_streamline=yes
Get-ChildItem .\bin\*console.exe
```

The MSVC commands above are a setup example; the tested local build uses
LLVM-MinGW as described below. Resolve
build prerequisites against the pinned source and its build output. Record
the compiler, SCons version, engine SHA and resulting binary filename; use
the actual console executable emitted by the build rather than assuming an
upstream release filename.

### Tested Windows binary built under WSL

The local trial cross-compiles with portable LLVM-MinGW
`20261020-ucrt-ubuntu-22.04-x86_64` (Clang 23.1.4), Python/SCons in a venv,
and this command in the pinned, patched engine checkout:

```bash
MINGW_PREFIX=/path/to/llvm-mingw /path/to/build-env/bin/scons \
  platform=windows target=editor arch=x86_64 use_mingw=yes use_llvm=yes \
  d3d12=no use_streamline=yes dev_build=no debug_symbols=no \
  optimize=speed lto=none -j8
```

`use_llvm=yes` selects the compiler. The resulting `.exe` is a native Windows
program, running Windows Vulkan and Streamline on the NVIDIA GPU. WSL is only
the build host; there is no VM or Linux graphics layer in the running client.
Copy both `godot.windows.editor.x86_64.llvm.exe` and its `.console.exe` wrapper
to `C:\Godot\rtx`. Keep `rtx-build.json` beside them with `source_commit`,
patch hash, compiler/build command, runtime versions and per-file SHA-256.
The startup report reads that optional manifest for the source identity;
the engine feature check independently verifies the material patch.

Obtain the matching Streamline SDK from
[NVIDIA's Streamline repository](https://github.com/NVIDIA-RTX/Streamline).
Use the SDK's documented runtime deployment files for the selected features,
including the interposer, feature plugins and required NGX DLLs, beside the
engine executable. Preserve the SDK's runtime layout and notices; copying
headers does not install the runtime. The fork explicitly loads
`sl.interposer.dll` through Windows LoadLibrary in
[streamline_context.cpp](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/drivers/streamline/streamline_context.cpp).
Use release runtime files for any distributed package. Record hashes and
versions of the deployed files, not just the engine executable.

One reproducibility detail needs attention: that same source initializes
Streamline with `eAllowOTA | eLoadDownloadedPlugins` and a hard-coded
application ID. Pinning DLLs alone therefore does not guarantee an unchanged
runtime. Record loaded plugin versions during testing; review the OTA policy
and application identity before distribution.

## Import and verify the engine

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
start its server. The PowerShell helper requires `-ExperimentalRtx` as well as `-Godot`
for the RTX trial. Passing only `-Godot` leaves the project on Compatibility.

Headless import detects script/resource problems. It cannot demonstrate RT
capabilities, successful DLSS initialization, visible rendering or performance.
Under WSL use the native Windows executable and Windows Python environment;
do not use Linux Mesa/software results to characterize Windows RTX performance.

## Experimental launch

Install the pinned Windows fork and matching Streamline runtime as described
above. The local default executable is
`C:\Godot\rtx\godot.windows.editor.x86_64.llvm.console.exe`; override it for
other builds. From WSL:

```bash
make run-rtx
make run-rtx RTX_QUALITY=quality
make run-rtx WINDOWS_RTX_GODOT='C:\path\to\fork_console.exe'
```

From Windows PowerShell:

```powershell
.\tools\run-windows.ps1 -Godot 'C:\path\to\fork_console.exe' -ExperimentalRtx -RtxQuality native
```

`native` uses scale 1.0; `quality` uses 0.66. Both use DLSS Ray Reconstruction
and leave Frame Generation off. Renderer and driver arguments precede `--`;
`--rtx --rtx-quality native|quality` follow it. For raster comparison, launch
the same fork with `--rendering-method forward_plus --rendering-driver vulkan`
and game argument `--outdoor-3d`, omitting `--rtx`.

Use an isolated game worktree for initial development-engine imports and a
separate application user directory during measurements. The launcher does
not automatically download or build the fork, change the default engine or
relaunch with a different renderer after failure. `fetch-godot` remains tied
to the upstream release. Use `make run` to return to the standard engine.

An in-game engine selector and packaged RTX exports are later work. A stock
export cannot gain the fork's renderer through a saved setting.

## Enable path tracing in a bounded 3D trial

The optional client helper is shared by the outdoor view and `home_first_person.gd`.
Keep fork-only APIs behind runtime discovery so standard Godot still parses
and runs the project. Avoid direct references to unknown `Streamline` classes
or fork-only enum symbols in scripts parsed by upstream Godot.

The helper verifies the selected rendering method and Vulkan device,
checks that Environment has `set_pathtracing_enabled`, and queries the rendering
device for ray tracing pipeline support. It obtains `Streamline` dynamically via
`Engine.has_singleton` / `Engine.get_singleton`, and queries `get_capability`
using constants discovered through ClassDB. The fork's
[Streamline reference](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/doc/classes/Streamline.xml)
exposes separate capabilities for DLSS, Ray Reconstruction, Frame Generation
and Reflex. Fail closed for missing APIs or capabilities and explain the
unavailable feature.

Configure the Environment assigned to the outdoor camera or interior WorldEnvironment.
Set path tracing through guarded `Object.call`/`set` operations. Initial values
for a measured trial are one sample per pixel, two bounces and DLSS Ray
Reconstruction, when available. The implementation clamps bounces to 1–8 in
[environment.cpp](https://github.com/NVIDIA-RTX/godot/blob/382d9d6bf0274af34b85d3cbcd98981de41cbd62/scene/resources/environment.cpp);
its XML description of zero bounces should not be treated as a supported
setting at this revision.

Configure DLSS on the selected 3D SubViewport, not only the root window. Discover
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
render checks, screenshots and the same performance scenes. Track the remaining
visual and performance gates in the
[outdoor scene readiness plan](rtx-scene-readiness.md). Steps 1–6 are already
complete; Step 7 records the experimental trial and its outstanding checks.
