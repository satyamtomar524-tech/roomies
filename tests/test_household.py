import copy
import unittest

from roommate.household import default_flat, summarize_flat, validate_flat


def household_data():
    return {"name": "Our flat", "is_demo": False,
            "members": [{"id": "me", "name": "Me"}, {"id": "amy", "name": "Amy"}],
            "inventory": [{"id": "mugs", "name": "Mugs", "category": "kitchen", "location": "Kitchen", "spot": "Upper shelf", "owner_id": None, "quantity": 3, "notes": ""}],
            "fridge": [{"id": "milk", "name": "Milk", "quantity": "1 litre", "storage": "fridge", "owner_id": "me", "status": "low", "best_before": "2026-10-04", "notes": ""}],
            "expenses": [{"id": "shop", "title": "Groceries", "amount_cents": 1001, "paid_by": "me", "split_between": ["me", "amy"], "date": "2026-09-30", "category": "groceries", "notes": ""}]}


class HouseholdTests(unittest.TestCase):
    def test_default_is_empty_and_has_no_invented_debts(self):
        flat = validate_flat(default_flat())
        self.assertTrue(flat["is_demo"])
        self.assertEqual(flat["members"], [{"id": "me", "name": "Me"}])
        self.assertEqual(flat["inventory"], [])
        self.assertEqual(flat["fridge"], [])
        self.assertEqual(flat["expenses"], [])
        self.assertEqual(summarize_flat(flat)["expenses"]["total_cents"], 0)

    def test_valid_data_normalizes_without_mutating_inputs(self):
        data = household_data()
        data["inventory"][0]["name"] = "  Mugs  "
        before = copy.deepcopy(data)
        flat = validate_flat(data)
        self.assertEqual(flat["inventory"][0]["name"], "Mugs")
        self.assertEqual(data, before)
        self.assertEqual(flat["expenses"][0]["amount_cents"], 1001)

    def test_flat_unknown_fields_and_wrong_types_are_rejected(self):
        for field, value in (("password", "secret"), ("is_demo", "false"), ("inventory", {}), ("members", [])):
            with self.subTest(field=field):
                data = household_data()
                data[field] = value
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_record_unknown_fields_are_rejected(self):
        for field in ("members", "inventory", "fridge", "expenses"):
            with self.subTest(field=field):
                data = household_data()
                data[field][0]["unexpected"] = True
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_ids_are_nonempty_unique_and_suitable_for_dom_controls(self):
        for field in ("members", "inventory", "fridge", "expenses"):
            for identity in ("", "an id with spaces", "../secret", "x" * 65, None):
                with self.subTest(field=field, identity=identity):
                    data = household_data()
                    data[field][0]["id"] = identity
                    with self.assertRaises(ValueError):
                        validate_flat(data)
            data = household_data()
            data[field].append(copy.deepcopy(data[field][0]))
            with self.assertRaises(ValueError):
                validate_flat(data)

    def test_removed_member_cannot_leave_orphan_owners_or_expenses(self):
        for field in ("inventory", "fridge"):
            with self.subTest(field=field):
                data = household_data()
                data[field][0]["owner_id"] = "missing"
                with self.assertRaises(ValueError):
                    validate_flat(data)
        data = household_data()
        data["members"] = data["members"][:1]
        with self.assertRaises(ValueError):
            validate_flat(data)

    def test_owner_must_be_null_or_a_member_id(self):
        for owner in ("", False, 1, []):
            with self.subTest(owner=owner):
                data = household_data()
                data["inventory"][0]["owner_id"] = owner
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_inventory_quantity_is_positive_bounded_integer(self):
        for quantity in (0, -1, 1.5, True, "2", 100001):
            with self.subTest(quantity=quantity):
                data = household_data()
                data["inventory"][0]["quantity"] = quantity
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_food_date_is_optional_but_calendar_exact_when_provided(self):
        for value in ("2026-02-30", "2026-2-1", "20260930", "today", "", False):
            with self.subTest(value=value):
                data = household_data()
                data["fridge"][0]["best_before"] = value
                with self.assertRaises(ValueError):
                    validate_flat(data)
        data = household_data()
        data["fridge"][0]["best_before"] = None
        self.assertIsNone(validate_flat(data)["fridge"][0]["best_before"])
        data["fridge"][0]["best_before"] = "2028-02-29"
        self.assertEqual(validate_flat(data)["fridge"][0]["best_before"], "2028-02-29")

    def test_food_status_storage_and_quantities_are_explicit(self):
        for field, value in (("status", "fresh"), ("storage", "garage"), ("quantity", 5), ("notes", "x" * 1001)):
            with self.subTest(field=field):
                data = household_data()
                data["fridge"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_list_limits_prevent_unbounded_imports(self):
        for field, count in (("members", 21), ("inventory", 501), ("fridge", 301), ("expenses", 501)):
            with self.subTest(field=field):
                data = household_data()
                data[field] = [copy.deepcopy(data[field][0]) for _ in range(count)]
                with self.assertRaises(ValueError):
                    validate_flat(data)

    def test_summary_counts_locations_stock_and_exact_cent_balances(self):
        data = household_data()
        data["inventory"].append({"id": "books", "name": "Books", "quantity": 5, "location": "Bedroom"})
        data["fridge"].append({"id": "rice", "name": "Rice", "status": "out", "storage": "pantry"})
        result = summarize_flat(data)
        self.assertEqual(result["inventory_count"], 2)
        self.assertEqual(result["inventory_quantity"], 8)
        self.assertEqual(result["locations"], ["Bedroom", "Kitchen"])
        self.assertEqual(result["fridge_counts"], {"stocked": 0, "low": 1, "out": 1})
        self.assertEqual(result["expenses"]["total_cents"], 1001)
        self.assertEqual(sum(balance["balance_cents"] for balance in result["expenses"]["balances"]), 0)


if __name__ == "__main__":
    unittest.main()
