// Shared parameters for the first-pass DeskBot enclosure.
// All lengths are millimetres. Parameters marked UNVERIFIED are estimates
// or allowances to be measured against the physical parts before printing.

// Output selector is in deskbot_enclosure.scad:
// "assembly", "base", "pan_bracket", "tilt_bracket", "head_shell", "back_cover".

// Display choice. "compact_13" is the recommended first prototype.
// The compact SH1106 board outline varies by supplier; these defaults are
// UNVERIFIED. The V2 2.42-inch SSD1309 board is documented as 70 x 48 mm.
display_choice = "compact_13"; // "compact_13" or "v2_242"
display_board_width = display_choice == "v2_242" ? 70 : 35; // compact: UNVERIFIED
display_board_height = display_choice == "v2_242" ? 48 : 35; // compact: UNVERIFIED
display_board_thickness = 3.0; // UNVERIFIED; board, connector and solder allowance
display_aperture_width = display_choice == "v2_242" ? 57 : 29; // compact active window: UNVERIFIED
display_aperture_height = display_choice == "v2_242" ? 29 : 15; // compact active window: UNVERIFIED
display_edge_allowance = 7;
display_center_z = -5;

// Enclosure and print allowances.
wall_thickness = 2.4;
minimum_wall_thickness = 2.0;
assembly_clearance = 0.35; // initial FDM allowance; tune for printer/material
cover_clearance = 0.30;
corner_radius = 8;
boss_diameter = 9.0; // UNVERIFIED; leaves >=2 mm around the provisional insert bore
screw_clearance_diameter = 3.2; // M3 nominal clearance; verify printer
insert_outer_diameter = 4.6; // UNVERIFIED; select heat-set insert first
insert_depth = 4.0; // UNVERIFIED

// Actual TowerPro MG90S dimensions from TowerPro's product specification.
// The repository specifies MG90S-class parts, but clone/vendor dimensions can
// differ. Keep these editable and measure both servos before fitting.
servo_case_length = 22.8;
servo_case_width = 12.2;
servo_case_height = 28.5;
servo_fit_clearance = 0.6;
servo_mount_tab_length = 32.0; // UNVERIFIED allowance
servo_mount_hole_spacing = 27.0; // UNVERIFIED; confirm drawing/physical servo
servo_mount_hole_diameter = 2.2; // UNVERIFIED

// Controller. The main Seeed XIAO ESP32S3 board outline is documented as
// 21 x 17.8 mm; the Sense expansion/camera stack is documented as 15 mm high.
xiao_width = 21;
xiao_depth = 17.8;
xiao_stack_height = 15; // stack height with Sense expansion; documented

// Camera aperture/board placement. Camera is on the XIAO Sense board, but its
// exact lens location and variant are not fixed by the repository.
camera_offset_x = 0; // UNVERIFIED
camera_offset_z = display_center_z + display_board_height / 2 + 5; // UNVERIFIED
camera_opening_diameter = 8; // UNVERIFIED; measure lens bezel, not sensor die
camera_tunnel_length = 8; // UNVERIFIED unobstructed optical clearance

// MAX98357A module is a generic clone in the repository; exact PCB outline is
// unknown. This is only a configurable reserve volume, not a selected footprint.
amplifier_width = 23; // UNVERIFIED
amplifier_height = 18; // UNVERIFIED
amplifier_depth = 4; // UNVERIFIED incl. header/solder allowance

// Head dimensions adjust for display footprint. Compact dimensions target the
// 100-120 mm overall height; the large-screen option will grow the head.
head_width = max(56, display_board_width + 16);
head_height = max(62, display_board_height + 25);
head_depth = 46;
head_pivot_offset_z = -7; // UNVERIFIED relative to head centre
head_pivot_diameter = screw_clearance_diameter; // M3 pivot passage; horn/bushing interface unverified
head_shell_inner_depth = head_depth - 2 * wall_thickness;
head_screw_inset = 6.7;
back_cover_thickness = 2.4;
back_cover_y = head_depth / 2 + back_cover_thickness / 2;

// Repository's Dayton Audio CE32A-8 speaker specification: 32 mm overall
// diameter, 15.5 mm depth and 19 mm baffle cutout. Check the specific revision.
speaker_diameter = 32;
speaker_depth = 15.5;
speaker_cutout_diameter = 19;
speaker_center_y = head_depth / 2 - speaker_depth / 2;
speaker_center_z = -7;
// Camera cutout coordinates are relative to the head centre.
// Screen centre coordinates are also relative to the head centre.

// Base and pan interface.
base_diameter = 82; // UNVERIFIED envelope; stable-base study only
base_height = 32; // UNVERIFIED
base_corner_radius = 9;
base_wall = wall_thickness;
base_floor = 2.8;
base_cover_thickness = 2.4;
base_ballast_diameter = 58; // UNVERIFIED; ballast material/mass not selected
base_ballast_depth = 8; // UNVERIFIED
base_ballast_clearance = 0.5;
usb_c_opening_width = 10; // UNVERIFIED breakout dimensions
usb_c_opening_height = 5; // UNVERIFIED breakout dimensions
usb_c_center_z = 10;
usb_c_rear_y = base_diameter / 2;
base_mount_bolt_circle = 54; // UNVERIFIED
pan_pivot_diameter = 8; // UNVERIFIED; pan bearing/shaft is not selected
pan_bolt_circle = base_mount_bolt_circle; // Shared pattern; actuator interface remains unverified.
pan_bracket_thickness = 4;
pan_bracket_diameter = 68; // UNVERIFIED; leaves material around the 54 mm bolt circle.
neck_post_height = 11; // UNVERIFIED; compact post length for height study
neck_post_outer_diameter = 14; // UNVERIFIED
neck_wire_passage_diameter = 7; // UNVERIFIED; verify connector passage
neck_post_flange_diameter = 36; // UNVERIFIED mount flange at tilt cradle
neck_post_flange_thickness = 3; // UNVERIFIED
pan_hub_height = 4;
tilt_cradle_thickness = 3;
pan_bracket_post_start_z = base_height + pan_bracket_thickness + pan_hub_height;
neck_post_top_z = pan_bracket_post_start_z + neck_post_height;
tilt_axis_z = neck_post_top_z + servo_case_height + tilt_cradle_thickness;
pan_bracket_top_z = tilt_axis_z;
head_center_z = tilt_axis_z - head_pivot_offset_z;
target_overall_height = 120; // desired envelope, not a verified fit claim

// Tilt cradle envelopes. The existing firmware's axes are limited to ±95°
// pan and ±85° tilt; this CAD model does not validate servo collision limits.
tilt_cradle_width = head_width + 6; // UNVERIFIED crossbar width
tilt_cradle_depth = 29; // UNVERIFIED
tilt_pivot_spacing = head_width;
tilt_servo_clearance = 0.6;

touch_electrode_enabled = false;
touch_electrode_width = 18; // UNVERIFIED
touch_electrode_height = 12; // UNVERIFIED
touch_electrode_center_z = head_height / 2 - 8; // UNVERIFIED, behind forehead skin
touch_electrode_center_x = head_width / 2 - wall_thickness - 1 - touch_electrode_width / 2; // UNVERIFIED

// Derived component envelope locations, all except documented component sizes
// are layout hypotheses to be checked against the real assembled hardware.
display_center_y = -head_depth / 2 + wall_thickness + display_board_thickness / 2 + 1;
xiao_center_y = -head_depth / 2 + wall_thickness + xiao_stack_height / 2; // UNVERIFIED
xiao_center_z = camera_offset_z + 4; // UNVERIFIED board/lens alignment
amplifier_center_x = head_width / 2 - wall_thickness - amplifier_width / 2 - 1; // UNVERIFIED
amplifier_center_y = 0; // UNVERIFIED
amplifier_center_z = -10; // UNVERIFIED

// Print preview/display quality.
preview_fn = 48;

// Derived checks visible as warnings in OpenSCAD console.
assert(wall_thickness >= minimum_wall_thickness,
       "Configured wall_thickness is below minimum_wall_thickness");
assert(base_floor >= minimum_wall_thickness,
       "Base floor is thinner than minimum_wall_thickness");
assert(back_cover_thickness >= minimum_wall_thickness,
       "Back cover is thinner than minimum_wall_thickness");
assert(boss_diameter >= insert_outer_diameter + 2 * minimum_wall_thickness,
       "Boss wall around the insert bore is below minimum_wall_thickness");
assert(base_ballast_clearance + wall_thickness >= minimum_wall_thickness,
       "Ballast retaining ring is thinner than minimum_wall_thickness");
assert(neck_post_outer_diameter >= neck_wire_passage_diameter
                                     + 2 * minimum_wall_thickness,
       "Neck-post wall is thinner than minimum_wall_thickness");
assert(display_aperture_width + 2 * minimum_wall_thickness <= head_width,
       "Display aperture leaves insufficient head side wall");
assert(display_aperture_height <= head_height - 2 * minimum_wall_thickness,
       "Display aperture leaves insufficient head top/bottom wall");
assert(display_choice == "compact_13" || display_choice == "v2_242",
       "display_choice must be compact_13 or v2_242");
