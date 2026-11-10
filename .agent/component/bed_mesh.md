# Component: Bed mesh (`[bed_mesh]`)

> **Implemented status:** Z compensation from a probed mesh through the
> Remora-m8p `compensation` HAL component (`LinuxCNC/Components/
> Compensation/compensation.py`, installed as `remora-compensation` by
> `scripts/install_hal_components.sh`, needs `python3-numpy` /
> `python3-scipy`). Code: `BedMeshHalMapper`, `BedMeshWebguiMapper`,
> `PauseInspectWebguiMapper` (shared Z offset), `BedMeshService` (system:
> files; machine: on / off pin), the Bed Mesh page (`BedMeshView.vue`).
> Tests: `test_bed_mesh.py`, `test-bed-mesh-ui.ts`.
>
> The component needs fixes before it works: `compensation.py.patch`
> next to this file (python3 shebang, OUT pins for `scale` / `clear`,
> int `counts`, wait for the mesh file, RESET that does not hang).

## 1. INGESTION (Hand-Written CFG)

```cfg
[bed_mesh]
probe_count: 3, 3      // (Optional) probe grid X, Y — or one value for both; >= 3, default 3, 3
mesh_min: 10, 10       // (Optional) probed area X, Y where the probe touches (the nozzle goes [probe] x_offset, y_offset away); default the X / Y travel
mesh_max: 190, 190
speed: 50              // (Optional) XY travel between points, mm/s, default 50
horizontal_move_z: 5   // (Optional) machine Z between points, default 5
probe_speed: 5         // (Optional, not Klipper) G38.2 feed, mm/s, default 5
zero_reference_position: 100, 100  // (Optional) the mesh is 0 here (bilinear); default: raw heights
```

Klipper's other `[bed_mesh]` keys (`fade_*`, `algorithm`,
`mesh_pps`, ...) are not accepted yet. Probing needs a `[probe]`.

## 2. hardware.json

```json
"bed_mesh": { "probe_count": [3, 3] }
```

`null` without `[bed_mesh]`.

## 3. COMPILATION

machine.hal (`BedMeshHalMapper`):

```hal
loadusr -Wn compensation python3 /usr/local/bin/remora-compensation <repo>/machine_config/bed_mesh_active.txt cubic
loadrt conv_bit_float names=z-lift-float
loadrt conv_s32_float names=bed-mesh-float
loadrt sum2 names=z-eoffset-sum
loadrt conv_float_s32 names=z-eoffset-counts
setp compensation.fade-height 0
setp z-eoffset-sum.gain0 1000            # the pause lift: 1 mm
setp z-eoffset-sum.gain1 1               # the mesh: compensation.counts, 0.001 mm each
net bed-mesh-counts compensation.counts => bed-mesh-float.in
net bed-mesh-offset bed-mesh-float.out => z-eoffset-sum.in1
net z-lift-counts z-lift-float.out => z-eoffset-sum.in0
net z-eoffset-total z-eoffset-sum.out => z-eoffset-counts.in
net z-eoffset-counts z-eoffset-counts.out => axis.z.eoffset-counts
net bed-mesh-eoffset axis.z.eoffset => compensation.eoffset
net bed-mesh-limited motion.eoffset-limited => compensation.eoffset-limited
```

Z has one external offset input and Pause & Inspect lifts Z through it
as well, so both are summed in 0.001 mm counts. webgui_connections.hal
(`BedMeshWebguiMapper`, `PauseInspectWebguiMapper.to_lines(bed_mesh=True)`):

```hal
setp axis.z.eoffset-enable 1
setp axis.z.eoffset-scale 0.001
net inspect-z-lift-bit webgui.inspect-z-lift => z-lift-float.in
net bed-mesh-enable webgui.bed-mesh-enable => compensation.enable-in
net bed-mesh-x halui.axis.x.pos-relative => compensation.x-pos
net bed-mesh-y halui.axis.y.pos-relative => compensation.y-pos
net bed-mesh-z halui.axis.z.pos-relative => compensation.z-pos
```

`[AXIS_Z] OFFSET_AV_RATIO` (every generated INI) gives the offset its
velocity / acceleration budget.

## 4. MESHES (runtime)

- `machine_config/bed_meshes/<name>.txt`: one `x y z` line per probe
  point on a regular grid (gridprobe format), git-ignored.
- `machine_config/bed_mesh_active.txt`: the selected mesh, first line
  `# mesh: <name>`. The component reloads it when compensation is
  switched on. Generating a `[bed_mesh]` machine creates a flat mesh
  named `flat` over `probe_count` and the X / Y limits if none is active.
- `/api/v1/modules/bedmesh` (system service): list, read, save, create
  (flat), delete (not the active one), activate.
- `/api/v1/bedmesh/enable` (machine backend): `webgui.bed-mesh-enable`.


Console: every probed point (X, Y, height), the zero reference and each
mesh row under DEBUG; one INFO line when the mesh is saved and active
(its range).

## 5. PROBING (`BED_MESH_CALIBRATE`)

`backend/machine/services/BedMeshProbeService.py`, the same MDI probe
moves as Z tilt (`services/Probing.py`): X, Y and Z homed, compensation
switched off (its offset back to 0), then per point of `probe_count` over
`mesh_min` ... `mesh_max` — a zig-zag, row by row — `G53 G1 X Y`,
`G91 G38.2` down to `[stepper_z] position_min` (relative from the travel height: LinuxCNC allows `G53` only with `G0`/`G1`), `G90`, the height from
`stat.probed_position`, back to `horizontal_move_z`. The heights (less
the one at `zero_reference_position`) are saved as
`bed_meshes/<profile>.txt`, made the active mesh, and compensation is
switched on (the component reloads it). A probe that does not trigger
stops it, nothing is saved, compensation is as it was.

Run it with:

* `BED_MESH_CALIBRATE [PROFILE=<name>]` (default `default`) in MDI, a
  `.macro` line or the `[homing_override]` routine;
* the Bed Mesh page's "Probe mesh" (the name field is the profile);
* `POST /api/v1/bedmesh/calibrate {"profile": "..."}`, `GET` for "running";
* `G29` (MDI, or a print's start G-code): `Z_TILT_ADJUST` when the
  machine has `[z_tilt]`, then `BED_MESH_CALIBRATE` (`LevelingService`).

Z = 0 is wherever Z was homed: with Z homed on the probe the raw heights
are already relative to that point; otherwise set
`zero_reference_position` to the point Z = 0 was set at.
