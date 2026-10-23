module head_shell() {
    // Shell is open at the rear for service and is closed by back_cover().
    difference() {
        union() {
            rounded_prism(head_width, head_depth, head_height, corner_radius);

            // Side pivot bosses are aligned to the tilt cradle.
            for (side = [-1, 1])
                translate([side * (head_width / 2 - wall_thickness / 2),
                           0,
                           head_pivot_offset_z])
                    rotate([0, 90, 0])
                        cylinder(d=12, h=wall_thickness + 4,
                                 center=true, $fn=32);
        }

        // Main cavity opens at rear. Front wall remains at wall_thickness.
        translate([0, (wall_thickness + 1) / 2, 0])
            rounded_prism(head_width - 2 * wall_thickness,
                          head_depth - wall_thickness + 1,
                          head_height - 2 * wall_thickness,
                          max(1, corner_radius - wall_thickness));

        // Display viewing opening (rounded aperture; dimensions adjustable).
        translate([0,
                   -head_depth / 2 + wall_thickness / 2,
                   display_center_z])
            cube([display_aperture_width, wall_thickness + 3,
                  display_aperture_height], center=true);

        // Camera lens pass-through, aligned with configurable lens placement.
        translate([camera_offset_x,
                   -head_depth / 2 + wall_thickness / 2,
                   camera_offset_z])
            rotate([90, 0, 0])
                cylinder(d=camera_opening_diameter,
                         h=wall_thickness + camera_tunnel_length,
                         center=true, $fn=32);

        // Tilt pivot pass-throughs. They avoid closing the camera/display view.
        for (side = [-1, 1])
            translate([side * head_width / 2, 0, head_pivot_offset_z])
                rotate([0, 90, 0])
                    cylinder(d=head_pivot_diameter,
                             h=wall_thickness + 12, center=true, $fn=32);
    }

    // Rear cover bosses are added after the main cavity so they remain in the
    // open-back shell. Their centres tuck into the top/side walls.
    difference() {
        union()
            for (x = [-1, 1], z = [-1, 1])
                translate([x * (head_width / 2 - head_screw_inset),
                           head_depth / 2 - wall_thickness / 2 - 0.5,
                           z * (head_height / 2 - head_screw_inset)])
                    rotate([90, 0, 0])
                        cylinder(d=boss_diameter, h=wall_thickness + 1,
                                 center=true, $fn=24);

        // Through-holes are symmetric so the cover screws enter from outside.
        for (x = [-1, 1], z = [-1, 1])
            translate([x * (head_width / 2 - head_screw_inset),
                       head_depth / 2 - wall_thickness / 2 - 0.5,
                       z * (head_height / 2 - head_screw_inset)])
                rotate([90, 0, 0])
                    cylinder(d=insert_outer_diameter,
                             h=wall_thickness + 4, center=true, $fn=24);
    }
}
