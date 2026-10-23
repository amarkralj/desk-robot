module pan_bracket() {
    difference() {
        union() {
            cylinder(d=pan_bracket_diameter, h=pan_bracket_thickness,
                     center=false, $fn=preview_fn);
            // Hub provides a configurable mechanical interface; it is not a
            // modeled/validated MG90S spline, gear, bearing, or turntable.
            translate([0, 0, pan_bracket_thickness])
                cylinder(d=18, h=pan_hub_height, center=false, $fn=32);
        }

        translate([0, 0, -1])
            cylinder(d=pan_pivot_diameter, h=pan_bracket_thickness + 7,
                     center=false, $fn=32);
        translate([0, 0, -1])
            cylinder(d=neck_wire_passage_diameter + 2 * assembly_clearance,
                     h=pan_bracket_thickness + pan_hub_height + 2,
                     center=false, $fn=32);

        for (a = [45, 135, 225, 315])
            translate([cos(a) * pan_bolt_circle / 2,
                       sin(a) * pan_bolt_circle / 2,
                       pan_bracket_thickness / 2])
                cylinder(d=screw_clearance_diameter,
                         h=pan_bracket_thickness + 1, center=true, $fn=20);

        // Four radial slots provide a first-pass adjustable attachment pattern.
        // They are not a substitute for matching the actual servo horn.
        for (a = [0, 90, 180, 270])
            rotate([0, 0, a])
                translate([8, 0, pan_bracket_thickness / 2])
                    hull() {
                        translate([-2, 0, 0])
                            cylinder(d=screw_clearance_diameter,
                                     h=pan_bracket_thickness + 1, center=true, $fn=20);
                        translate([2, 0, 0])
                            cylinder(d=screw_clearance_diameter,
                                     h=pan_bracket_thickness + 1, center=true, $fn=20);
                    }
    }
}

module neck_post() {
    difference() {
        union() {
            cylinder(d=neck_post_outer_diameter, h=neck_post_height, center=false, $fn=32);
            translate([0, 0, neck_post_height - neck_post_flange_thickness])
                cylinder(d=neck_post_flange_diameter, h=neck_post_flange_thickness,
                         center=false, $fn=48);
        }
        translate([0, 0, -1])
            cylinder(d=neck_wire_passage_diameter + 2 * assembly_clearance,
                     h=neck_post_height + 2, center=false, $fn=24);

        // Two configurable M3 attachment clearances through the post flange.
        for (x = [-14, 14])
            translate([x, 0, neck_post_height - neck_post_flange_thickness / 2])
                cylinder(d=screw_clearance_diameter,
                         h=neck_post_flange_thickness + 1, center=true, $fn=20);
    }
}
