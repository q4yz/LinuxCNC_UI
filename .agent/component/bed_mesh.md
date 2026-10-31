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
```

Klipper's other `[bed_mesh]` keys (`mesh_min` / `mesh_max`, `fade_*`,
`algorithm`, ...) are not accepted yet.

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

Probing a mesh (a probe program over `probe_count`) is not implemented
yet: create a flat mesh and edit it, or write probe results into
`bed_meshes/`.
