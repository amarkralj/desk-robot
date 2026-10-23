/*
 * DeskBot parametric first-pass enclosure.
 * Units: millimetres. Front faces toward negative Y; Z is vertical.
 *
 * This is a fit-study, not a print-ready or validated mechanical design.
 * Review README.md before exporting any part.
 */
include <parameters.scad>
include <base.scad>
include <pan_bracket.scad>
include <tilt_bracket.scad>
include <head_shell.scad>
include <back_cover.scad>

// Choose "assembly", "base", "pan_bracket", "tilt_bracket",
// "head_shell", or "back_cover" before exporting an STL.
part = "assembly";
show_component_envelopes = true;
echo("Estimated overall height (mm):", head_center_z + head_height / 2);

module component_envelopes() {
    // These simple solids indicate reserved volumes only; they are not CAD
    // models of the electronic modules and are not a fit guarantee.
    color([0.2, 0.7, 0.9, 0.45])
        translate([0, xiao_center_y, head_center_z + xiao_center_z])
            cube([xiao_width, xiao_stack_height, xiao_depth], center=true);
    color([0.95, 0.65, 0.15, 0.4])
        translate([0, display_center_y, head_center_z + display_center_z])
            cube([display_board_width, display_board_thickness, display_board_height], center=true);
    color([0.7, 0.4, 0.85, 0.45])
        translate([0, speaker_center_y, head_center_z + speaker_center_z])
            rotate([90, 0, 0])
                cylinder(d=speaker_diameter, h=speaker_depth, center=true, $fn=48);
    color([0.9, 0.25, 0.2, 0.45])
        translate([0, 0, base_floor + servo_case_height / 2])
            cube([servo_case_length, servo_case_width, servo_case_height], center=true);
    color([0.9, 0.25, 0.2, 0.45])
        translate([0, 0, tilt_axis_z - servo_case_height / 2])
            cube([servo_case_length, servo_case_width, servo_case_height], center=true);
    color([0.25, 0.8, 0.45, 0.45])
        translate([amplifier_center_x, amplifier_center_y, head_center_z + amplifier_center_z])
            cube([amplifier_width, amplifier_depth, amplifier_height], center=true);
    if (touch_electrode_enabled)
        touch_electrode_envelope();
}

module assembly() {
    color([0.19, 0.22, 0.27])
        translate([0, 0, base_height / 2])
            base_shell();
    color([0.34, 0.40, 0.47])
        translate([0, 0, base_height])
            pan_bracket();
    color([0.36, 0.43, 0.49])
        translate([0, 0, pan_bracket_post_start_z])
            neck_post();
    color([0.48, 0.54, 0.60])
        translate([0, 0, tilt_axis_z])
            tilt_bracket();
    color([0.23, 0.27, 0.33])
        translate([0, 0, head_center_z])
            head_shell();
    color([0.32, 0.37, 0.43])
        translate([0, back_cover_y, head_center_z])
            back_cover();
    if (show_component_envelopes)
        component_envelopes();
}

if (part == "assembly") assembly();
else if (part == "base") base_shell();
else if (part == "pan_bracket") pan_bracket();
else if (part == "tilt_bracket") tilt_bracket();
else if (part == "head_shell") head_shell();
else if (part == "back_cover") back_cover();
else assert(false, str("Unknown part: ", part));
