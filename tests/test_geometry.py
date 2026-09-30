import copy
import math
import unittest

from roommate.geometry import ValidationError, analyse_room, find_positions, validate_room
from roommate.storage import demo_room


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.room = demo_room()

    def item(self, identity="bed"):
        return next(item for item in self.room["items"] if item["id"] == identity)

    def codes(self):
        return {issue["code"] for issue in analyse_room(self.room)["issues"]}

    def test_illustrative_room_is_valid_and_area_balances(self):
        result = analyse_room(self.room)
        self.assertTrue(result["valid"])
        self.assertEqual(result["area_m2"], 10.5)
        self.assertEqual(result["occupied_m2"], 2.8)
        self.assertEqual(result["reserved_m2"], .605)
        self.assertAlmostEqual(result["area_m2"], result["occupied_m2"] + result["reserved_m2"] + result["free_m2"])

    def test_nonfinite_boolean_and_unknown_input_are_rejected(self):
        for value in (math.nan, math.inf, True, "300"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_room({**self.room, "width_cm": value})
        with self.assertRaises(ValidationError):
            validate_room({**self.room, "secret": 1})

    def test_duplicate_item_ids_are_rejected(self):
        self.room["items"].append(copy.deepcopy(self.item()))
        with self.assertRaises(ValidationError):
            validate_room(self.room)

    def test_room_colors_require_six_digit_hex_values(self):
        self.room["wall_color"] = "#ABC123"
        self.assertEqual(validate_room(self.room)["wall_color"], "#abc123")
        for color in ("red", "#123", "url(https://example.com/image)", None):
            with self.subTest(color=color), self.assertRaises(ValidationError):
                validate_room({**self.room, "floor_color": color})

    def test_touching_edges_do_not_overlap(self):
        desk = self.item("desk")
        desk.update(x_cm=120, y_cm=200)
        self.assertNotIn("overlap", self.codes())

    def test_owned_and_planned_floor_items_collide(self):
        self.item("desk").update(x_cm=100, y_cm=200)
        result = analyse_room(self.room)
        self.assertFalse(result["valid"])
        self.assertIn("overlap", self.codes())

    def test_rotation_swaps_external_footprint(self):
        bed = self.item()
        bed.update(x_cm=150, y_cm=150, rotation=90)
        self.assertIn("out_of_bounds", self.codes())
        bed["x_cm"] = 100
        self.assertNotIn("out_of_bounds", self.codes())

    def test_overlap_and_outside_area_are_clipped_not_double_counted(self):
        self.room["items"] = [self.item()]
        duplicate = copy.deepcopy(self.item())
        duplicate.update(id="bed2", status="planned")
        self.room["items"].append(duplicate)
        result = analyse_room(self.room)
        self.assertEqual(result["reserved_m2"], 0)
        duplicate.update(x_cm=-60, y_cm=125)
        self.assertEqual(analyse_room(self.room)["free_m2"], 8.1)

    def test_conservative_inward_door_zone_blocks_furniture(self):
        self.item("desk").update(x_cm=0, y_cm=0)
        self.assertIn("door_clearance", self.codes())
        self.room["openings"][0]["swing"] = "out"
        self.assertNotIn("door_clearance", self.codes())

    def test_openings_must_fit_the_wall(self):
        self.room["openings"][0]["offset_cm"] = 290
        self.assertIn("opening_bounds", self.codes())

    def test_fixed_obstacle_collides_and_counts_in_occupied_area(self):
        self.room["openings"].append({"id": "radiator", "kind": "obstacle", "wall": "south", "offset_cm": 140, "width_cm": 40, "depth_cm": 20, "swing": "none"})
        self.assertAlmostEqual(analyse_room(self.room)["occupied_m2"], 2.88)
        self.item("desk").update(x_cm=140, y_cm=290)
        self.assertIn("fixed_obstacle", self.codes())

    def test_clearance_is_a_preference_warning(self):
        self.item("desk").update(x_cm=120, y_cm=200, clearance_cm=10)
        result = analyse_room(self.room)
        self.assertTrue(result["valid"])
        self.assertIn("preferred_clearance", self.codes())

    def test_surface_coordinates_are_local_and_checked(self):
        self.item("lamp")["x_cm"] = 100
        self.assertIn("surface_bounds", self.codes())
        self.item("lamp").update(x_cm=85, parent_id="missing")
        self.assertIn("surface_parent", self.codes())

    def test_surface_items_collide_with_each_other(self):
        another = copy.deepcopy(self.item("lamp"))
        another.update(id="second-lamp", name="Second lamp")
        self.room["items"].append(another)
        self.assertIn("surface_overlap", self.codes())

    def test_surface_height_includes_the_parent(self):
        self.item("lamp")["height_cm"] = 180
        self.assertIn("too_tall", self.codes())

    def test_rotated_parent_uses_its_actual_surface_footprint(self):
        self.item("desk").update(rotation=90, x_cm=200, y_cm=150)
        self.assertIn("surface_bounds", self.codes())
        self.item("lamp").update(x_cm=30, y_cm=85)
        self.assertNotIn("surface_bounds", self.codes())

    def test_suggested_parent_rotation_preserves_surface_reservations(self):
        suggestions = find_positions(self.room, "desk")
        self.assertTrue(suggestions)
        self.assertTrue(all(suggestion["rotation"] == 0 for suggestion in suggestions))
        for suggestion in suggestions:
            self.item("desk").update({key: suggestion[key] for key in ("x_cm", "y_cm", "rotation")})
            self.assertTrue(analyse_room(self.room)["valid"])

    def test_tall_child_prevents_suggestions_for_its_parent(self):
        self.item("lamp")["height_cm"] = 180
        self.assertEqual(find_positions(self.room, "desk"), [])

    def test_overlay_does_not_consume_floor_twice(self):
        rug = copy.deepcopy(self.item())
        rug.update(id="rug", name="Rug", placement="overlay")
        before = analyse_room(self.room)
        self.room["items"].append(rug)
        after = analyse_room(self.room)
        self.assertTrue(after["valid"])
        self.assertEqual(before["free_m2"], after["free_m2"])

    def test_wall_item_does_not_collide_with_floor_item(self):
        shelf = copy.deepcopy(self.item())
        shelf.update(id="shelf", name="Wall shelf", placement="wall", height_cm=30)
        self.room["items"].append(shelf)
        self.assertTrue(analyse_room(self.room)["valid"])

    def test_suggestions_are_valid_and_leave_input_unchanged(self):
        before = copy.deepcopy(self.room)
        suggestions = find_positions(self.room, "desk")
        self.assertTrue(1 <= len(suggestions) <= 5)
        self.assertEqual(self.room, before)
        for suggestion in suggestions:
            self.item("desk").update({key: suggestion[key] for key in ("x_cm", "y_cm", "rotation")})
            self.assertTrue(analyse_room(self.room)["valid"])

    def test_oversized_item_has_no_suggestion(self):
        self.item("desk").update(width_cm=400, depth_cm=400)
        self.assertEqual(find_positions(self.room, "desk"), [])

    def test_locked_and_unknown_item_reject_suggestions(self):
        self.item("desk")["locked"] = True
        for identity in ("desk", "missing"):
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                find_positions(self.room, identity)


if __name__ == "__main__":
    unittest.main()
