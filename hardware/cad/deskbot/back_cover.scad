module back_cover() {
    // Local XY maps to head XZ, and extrusion thickness maps along Y.
    rotate([90, 0, 0])
        difference() {
            rounded_prism(head_width - 2 * cover_clearance,
                          head_height - 2 * cover_clearance,
                          back_cover_thickness,
                          max(2, corner_radius - 2));

            // CE32A-8 acoustic aperture and shallow speaker-frame recess.
            translate([0, speaker_center_z, 0])
                cylinder(d=speaker_cutout_diameter, h=back_cover_thickness + 1,
                         center=true, $fn=48);
            // Open grille vents around the baffle aperture.
            for (a = [0 : 30 : 330])
                rotate([0, 0, a])
                    translate([12, speaker_center_z, 0])
                        hull() {
                            translate([-2, 0, 0])
                                cylinder(d=2, h=back_cover_thickness + 1,
                                         center=true, $fn=16);
                            translate([2, 0, 0])
                                cylinder(d=2, h=back_cover_thickness + 1,
                                         center=true, $fn=16);
                        }

            // Cover screws. Boss/insert positions must be verified after preview.
            for (x = [-1, 1], z = [-1, 1])
                translate([x * (head_width / 2 - head_screw_inset),
                           z * (head_height / 2 - head_screw_inset),
                           0])
                    cylinder(d=screw_clearance_diameter,
                             h=back_cover_thickness + 1, center=true, $fn=20);
        }
}

module touch_electrode_envelope() {
    // Assembly-preview volume only; no shell cutout or touch hardware implied.
    color([0.85, 0.65, 0.1, 0.5])
        translate([touch_electrode_center_x, -head_depth / 2 + wall_thickness + 0.6,
                   head_center_z + touch_electrode_center_z])
            cube([touch_electrode_width, 0.6, touch_electrode_height], center=true);
}
