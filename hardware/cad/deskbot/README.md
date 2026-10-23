# DeskBot parametric enclosure — first-pass fit study

This is a new, original OpenSCAD layout for the hardware described by this repository. There was no existing CAD, assembly model, or printable V2 body file in the checkout to reuse. It is an initial modular enclosure study, **not print-ready**: several board outlines, connector positions, mounting patterns, and motion interfaces are not specified in the repository and must be measured before producing functional parts.

## Recommended prototype and target size

The default model uses the compact 1.3-inch SH1106 option because the project documents that firmware can select it by setting `OLED_SSD1309_242` to `0` in `firmware/include/config.h`. The 1.3-inch module's exact PCB outline is not given in this repository. Its default 35 × 35 mm footprint and optical aperture are therefore clearly marked as unverified, configurable fit-study values in `parameters.scad`.

The compact configuration's estimated vertical envelope is approximately 120.5 mm using the 32 mm base, 11 mm hollow post, pan/tilt support stack and 62 mm head height. This is a CAD parameter calculation, not a hardware-confirmed assembled measurement. The large-display option uses the repository-documented 70 × 48 mm V2 SSD1309 board and automatically increases head width/height; that option is expected to exceed the compact height target.

## Files

- `deskbot_enclosure.scad` — assembly preview and part selector.
- `parameters.scad` — shared dimensions, clearances, display selection and provisional values.
- `base.scad` — hollow stable-base shell, ballast well, rear USB-C access and pan fastener pattern.
- `pan_bracket.scad` — adjustable pan stage, hollow neck post and initial horn/pivot interface.
- `tilt_bracket.scad` — servo cradle and side pivot support.
- `head_shell.scad` — rounded open-back head, display and camera openings, cover/pivot bosses.
- `back_cover.scad` — removable speaker/service cover with an acoustic opening and vents.

The assembly's colored component blocks are only reserved-space illustrations; they are not electronic-module CAD. Disable them with `show_component_envelopes = false` if they obscure the enclosure.

## Render and export

Open `deskbot_enclosure.scad` in OpenSCAD. Preview with **F5**, then use **F6** for a full CGAL render. The OpenSCAD console should show no assertion failures or non-manifold warnings.

To export each part separately:

1. Set `part` at the top of `deskbot_enclosure.scad` to one of `base`, `pan_bracket`, `tilt_bracket`, `head_shell`, or `back_cover`.
2. Press **F6**.
3. Choose **File → Export → Export as STL** and use a matching filename.
4. Reopen the `assembly` part and visually inspect whether covers, screw bosses, pivots, cable passages and component envelopes intersect correctly.

With the OpenSCAD command line, from this directory:

```sh
openscad -o /tmp/deskbot-base.stl -D 'part="base"' deskbot_enclosure.scad
openscad -o /tmp/deskbot-head.stl -D 'part="head_shell"' deskbot_enclosure.scad
openscad -o /tmp/deskbot-cover.stl -D 'part="back_cover"' deskbot_enclosure.scad
```

Do not slice or print a functional set until the physical-fit checklist below is complete.

### Render check performed

OpenSCAD 2026.10.11 rendered the default assembly and all five selectable printable parts with CGAL. Every render reported `Status: NoError` and a manifold 3D object. The compact assembly reported 3,546 vertices and 7,236 facets. The alternate 2.42-inch display assembly also rendered manifold with `NoError` and an estimated 126 mm height. The optional touch-electrode envelope variant rendered without geometry errors.

This verifies OpenSCAD geometry construction and mesh manifold status only. It does **not** verify physical component fit, servo movement/collision limits, screw accessibility, material strength, balance, or slicer support requirements. Component envelopes are provisional solids.

## Documented dimensions and sources

| Component | CAD value/reference | Evidence and qualification |
|---|---:|---|
| XIAO ESP32S3 Sense main board | 21 × 17.8 mm | Seeed's [XIAO ESP32-S3 getting-started page](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) lists 21 × 17.8 mm; the Sense version with expansion board is listed as 21 × 17.8 × 15 mm. Camera variants have changed over time. |
| MG90S servo | 22.8 × 12.2 × 28.5 mm | [TowerPro MG90S specification](https://www.towerpro.com.tw/product/mg90s-3/). The repository names MG90S-class servos; clones may differ, and the CAD's mounting-tab pattern is unverified. |
| V2 2.42-inch SSD1309 board | 70 × 48 mm | Explicitly documented in the repository [README](../../../README.md#what-you-need). |
| 1.3-inch SH1106 board | configurable; default 35 × 35 mm | Firmware option is documented by this repository; exact board outline is absent. Default is an unverified allowance and must be measured. |
| Dayton CE32A-8 speaker | 32 mm frame, 15.5 mm depth, 19 mm baffle cutout | [Dayton Audio product page](https://www.daytonaudio.com/product/1137/ce32a-8-1-1-4-mini-speaker-driver-8-ohm); check the physical revision and its drawing before finalizing the cover. |
| MAX98357A amplifier board | configurable; default 23 × 18 × 4 mm | The repository specifies generic low-cost clone boards, not a vendor/revision. All CAD values are unverified allowances. |
| Camera lens/board placement | configurable | The repository confirms the camera is on the Sense board but contains no dimensioned lens offset or mechanical drawing. Camera opening coordinates are unverified. |

## Dimensions still requiring physical measurement

Before fit/printability review, measure the exact parts and adjust `parameters.scad`:

- 1.3-inch SH1106 board outline, active display window, thickness, connector location, and mounting features. For the larger screen, confirm the purchased SSD1309 board matches the documented 70 × 48 mm.
- Actual XIAO Sense stack, camera lens centre, lens bezel diameter, board-to-board connector, and the desired board orientation. Confirm an unobstructed viewing cone through the camera hole throughout the tilt range.
- Both MG90S cases, mounting tabs/hole spacing, output spline/horn envelope, wire exit and servo lead bend radius.
- Existing pan gear dimensions and engagement geometry. The repository documents a 38:30 ratio but the printable gear profiles/diameters and full V2 CAD are not in this checkout; the CAD pan hub is only a configurable placeholder, not a working gear train.
- MAX98357A clone outline, connector/header height and wire routing.
- Speaker basket depth, mounting rim, and baffle cutout on the actual CE32A-8 revision.
- USB-C breakout outline and connector face position; 470 µF capacitor, diode and base-board footprints/height.
- Required M2/M3 screw lengths, heat-set insert OD/depth, head-cover boss positions and any screw-driver access.
- Wire bundle size/strain relief through the hollow neck and service loop required over both motion axes.
- Ballast puck material, exact weight, restraint method and base stability with the head at pan/tilt extremes.
- Touch-electrode material/size and placement, if pursued. Existing firmware has no touch input; this model does not claim a working sensor or pin.

The current SCAD includes configurable clearances, an internal ballast-retaining ring, hollow wiring path, removable rear head cover and configurable servo/camera/display parameters. It uses a parametric pan hub and a tilt-cradle layout, but does not reproduce the documented 38:30 pan gears because tooth module, pitch diameter, gear thickness, and bearing details are absent from this checkout. It does **not** establish servo collision clearance, pan gearing, structural strength, print orientation, or verified 100–120 mm physical fit. Check every part in a slicer and print small fit gauges before a complete enclosure.

## Firmware compatibility notes

This enclosure does not change firmware or pin assignments. The repository's documented V2 motion limits are pan ±95° and tilt ±85° (`firmware/include/config.h`); collision testing across these limits remains required. The compact OLED firmware setting is `OLED_SSD1309_242 0`; the existing V2 2.42-inch display uses `1`. The model does not promise unrestricted rotation, a touch sensor, or a physically verified identity-recognition camera placement.
