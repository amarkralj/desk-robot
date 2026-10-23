module rounded_prism(width, depth, height, radius) {
    linear_extrude(height=height, center=true, convexity=4)
        offset(r=radius)
            square([width - 2 * radius, depth - 2 * radius], center=true);
}

module base_shell() {
    difference() {
        union() {
            rounded_prism(base_diameter, base_diameter, base_height, base_corner_radius);
            // Bosses around the pan-stage fasteners are part of the printed shell.
            for (a = [45, 135, 225, 315])
                translate([cos(a) * base_mount_bolt_circle / 2,
                           sin(a) * base_mount_bolt_circle / 2,
                           base_height / 2 - 2])
                    cylinder(d=boss_diameter, h=4, center=true, $fn=24);
        }

        // Open interior while retaining a continuous floor and top deck.
        translate([0, 0, (base_floor - base_wall) / 2])
            rounded_prism(base_diameter - 2 * base_wall,
                          base_diameter - 2 * base_wall,
                          base_height - base_floor - base_wall,
                          max(1, base_corner_radius - base_wall));

        // Pan actuator envelope. Physical servo orientation and shaft interface
        // remain to be checked against the chosen MG90S and existing gear set.
        translate([0, 0, -base_height / 2 + base_floor
                            + (servo_case_height + 1) / 2])
            cube([servo_case_length + 2 * servo_fit_clearance,
                  servo_case_width + 2 * servo_fit_clearance,
                  servo_case_height + 1], center=true);

        // Rear USB-C access. Opening is deliberately oversized until breakout
        // board and connector shell are physically measured.
        translate([0, usb_c_rear_y, usb_c_center_z - base_height / 2])
            rotate([90, 0, 0])
                cube([usb_c_opening_width, usb_c_opening_height,
                      base_wall + 4], center=true);

        // Wiring rises through the rotating stage and hollow neck.
        translate([0, 0, 0])
            cylinder(d=neck_wire_passage_diameter + 2 * assembly_clearance,
                     h=base_height + 2, center=true, $fn=32);

        // Pan fastener clearances from the underside/top deck.
        for (a = [45, 135, 225, 315])
            translate([cos(a) * base_mount_bolt_circle / 2,
                       sin(a) * base_mount_bolt_circle / 2,
                       base_height / 2])
                cylinder(d=screw_clearance_diameter,
                         h=base_height + 2, center=true, $fn=20);
    }

    // Raised ballast retaining ring on the internal floor. Insert ballast
    // from above before installing the pan-stage parts.
    difference() {
        translate([0, 0, -base_height / 2 + base_floor + base_ballast_depth / 2 - 0.1])
            cylinder(d=base_ballast_diameter + 2 * base_ballast_clearance + 2 * wall_thickness,
                     h=base_ballast_depth, center=true, $fn=preview_fn);
        translate([0, 0, -base_height / 2 + base_floor + base_ballast_depth / 2 - 0.1])
            cylinder(d=base_ballast_diameter + 2 * base_ballast_clearance,
                     h=base_ballast_depth + 1, center=true, $fn=preview_fn);
    }
}
