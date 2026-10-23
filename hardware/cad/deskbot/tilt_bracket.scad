module tilt_bracket() {
    // Printed U cradle. Servo retaining straps/fasteners are intentionally
    // absent until the physical horn, screw pattern, and collision envelope
    // have been measured.
    difference() {
        union() {
            // Crossbar below the head supports the servo case.
            translate([0, 0, -servo_case_height - tilt_cradle_thickness / 2])
                cube([tilt_cradle_width, tilt_cradle_depth, tilt_cradle_thickness],
                     center=true);

            // Side arms rise to the head's two tilt pivots.
            for (side = [-1, 1])
                translate([side * (tilt_pivot_spacing / 2),
                           0,
                           -servo_case_height / 2])
                    cube([tilt_cradle_thickness, tilt_cradle_depth,
                          servo_case_height + tilt_cradle_thickness], center=true);

            // Pivot pads.
            for (side = [-1, 1])
                translate([side * (tilt_pivot_spacing / 2), 0, 0])
                    rotate([0, 90, 0])
                        cylinder(d=12, h=tilt_cradle_thickness + 2, center=true, $fn=32);
        }

        // Servo envelope, with additional adjustable fit allowance.
        translate([0, 0, -servo_case_height / 2])
            cube([servo_case_length + 2 * tilt_servo_clearance,
                  servo_case_width + 2 * tilt_servo_clearance,
                  servo_case_height], center=true);

        // Fasteners connect the cradle crossbar to the hollow neck-post flange.
        for (x = [-14, 14])
            translate([x, 0, -servo_case_height - tilt_cradle_thickness / 2])
                cylinder(d=screw_clearance_diameter,
                         h=tilt_cradle_thickness + 1, center=true, $fn=20);

        // Pivot fasteners, M3 clearance in the side pads.
        for (side = [-1, 1])
            translate([side * (tilt_pivot_spacing / 2), 0, 0])
                rotate([0, 90, 0])
                    cylinder(d=screw_clearance_diameter,
                             h=tilt_cradle_thickness + 4, center=true, $fn=20);

        // Tie/retainer slots to accept a future clamp strap.
        for (x = [-10, 10])
            translate([x, 0, -servo_case_height - tilt_cradle_thickness / 2])
                cube([2.5, tilt_cradle_depth + 1, tilt_cradle_thickness + 1], center=true);
    }
}
