# Kinematics: CoreXY (`[machine] kinematics: corexy`)

> **Implemented status:** the CoreXY math in HAL (`CoreXyHalMapper`), not
> LinuxCNC's `corexykins`: LinuxCNC stays `trivkins` with Cartesian
> joints, so homing, endstops and soft limits stay per axis. Stock
> `sum2` components (the Remora-m8p fork has no CoreXY component; a
> dedicated one could replace the four `sum2`s one for one). Remora
> (position-class) motion only. Tests: `test_corexy.py`.

## 1. INGESTION (Hand-Written CFG)

```cfg
[machine]
kinematics: corexy        // cartesian (default) | corexy

[stepper_x]               // motor A (Klipper's convention)
...
endstop_pin: PG6          // the X axis' home switch, as on a Cartesian machine
[stepper_y]               // motor B
...
```

`E_COREXY`: exactly one joint on X and on Y (no `[stepper_y1]`), and
`[stepper_x]` / `[stepper_y]` on a Remora board.

## 2. hardware.json

`"kinematics": "corexy"`.

## 3. COMPILATION

machine.ini: `KINEMATICS = trivkins` as always; `[JOINT_<X|Y>]
STEPGEN_MAXACCEL` doubled — it is the Remora step generator's limit,
i.e. per belt motor, and a motor sees up to the X plus the Y
acceleration (`A = X + Y`).

machine.hal (`RemoraStepperHalMapper` leaves out its direct `pos-cmd` /
`pos-fb` nets for joints X / Y; enables, scales, home switches unchanged):

```hal
loadrt sum2 names=corexy-a,corexy-b,corexy-x,corexy-y
addf corexy-a servo-thread         # ... after motion-controller, before remora.write
setp corexy-b.gain1 -1             # B = X - Y
setp corexy-x.gain0 0.5            # X = (A + B) / 2
setp corexy-x.gain1 0.5
setp corexy-y.gain0 0.5            # Y = (A - B) / 2
setp corexy-y.gain1 -0.5
net j0pos-cmd joint.0.motor-pos-cmd => corexy-a.in0 corexy-b.in0
net j1pos-cmd joint.1.motor-pos-cmd => corexy-a.in1 corexy-b.in1
net corexy-a-cmd corexy-a.out => remora.joint.0.pos-cmd
net corexy-b-cmd corexy-b.out => remora.joint.1.pos-cmd
net corexy-a-fb remora.joint.0.pos-fb => corexy-x.in0 corexy-y.in0
net corexy-b-fb remora.joint.1.pos-fb => corexy-x.in1 corexy-y.in1
net j0pos-fb corexy-x.out => joint.0.motor-pos-fb
net j1pos-fb corexy-y.out => joint.1.motor-pos-fb
```

Motor A / B are the Remora joints numbered like the X / Y joints, so
the step generators (`config.txt`) keep `[stepper_x]` / `[stepper_y]`'s
pins and scales. A motor turns the wrong way: invert its `dir_pin`, as
in Klipper.
