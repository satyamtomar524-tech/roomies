import copy
import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from roommate.expenses import monthly_bill_status, summarize_expenses, validate_monthly_bill, validate_repayment
from roommate.household import validate_flat
from roommate.storage import Storage
from tests.test_household import household_data


def repayment_data(**changes):
    return {"id": "payback", "from_id": "amy", "to_id": "me", "amount_cents": 500,
            "date": "2026-09-30", "notes": "Recorded by the user", **changes}


def monthly_bill_data(**changes):
    return {"id": "internet", "title": "Internet", "amount_cents": 3000, "paid_by": "me",
            "split_between": ["me", "amy"], "category": "utilities", "notes": "",
            "due_day": 31, "active": True, **changes}


class RepaymentTests(unittest.TestCase):
    def setUp(self):
        self.flat = household_data()

    def summary(self, repayments):
        return summarize_expenses(self.flat["expenses"], self.flat["members"], repayments)

    def test_repayment_clears_the_balance_without_inflating_spending(self):
        result = self.summary([repayment_data()])
        self.assertEqual(result["total_cents"], 1001)
        self.assertEqual([entry["balance_cents"] for entry in result["balances"]], [0, 0])
        self.assertEqual([entry["paid_cents"] for entry in result["balances"]], [1001, 0])
        self.assertEqual(result["settlements"], [])

    def test_partial_and_multiple_payments_leave_the_correct_balance(self):
        result = self.summary([repayment_data(amount_cents=200), repayment_data(id="second", amount_cents=100)])
        self.assertEqual(result["settlements"], [{"from_id": "amy", "to_id": "me", "amount_cents": 200}])

    def test_overpayment_reverses_the_remaining_balance(self):
        result = self.summary([repayment_data(amount_cents=600)])
        self.assertEqual(result["settlements"], [{"from_id": "me", "to_id": "amy", "amount_cents": 100}])
        self.assertEqual(sum(entry["balance_cents"] for entry in result["balances"]), 0)

    def test_invalid_repayments_cannot_change_the_ledger(self):
        changes = [{"amount_cents": value} for value in (0, -1, True, 1.5, "500", 100000001)]
        changes += [{"to_id": "amy"}, {"from_id": "missing"}, {"date": "2026-02-30"},
                    {"date": "20260930"}, {"notes": "x" * 1001}, {"unknown": 1}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_repayment(repayment_data(**change), self.flat["members"])

    def test_duplicate_ids_and_record_limits_are_rejected(self):
        for payments in ([repayment_data(), repayment_data()], [repayment_data(id=str(i)) for i in range(501)], {}):
            with self.subTest(payments=type(payments)), self.assertRaises(ValueError):
                self.summary(payments)

    def test_member_cannot_be_removed_while_payment_still_refers_to_them(self):
        self.flat.update(expenses=[], inventory=[], fridge=[], repayments=[repayment_data()])
        self.flat["members"] = self.flat["members"][:1]
        with self.assertRaises(ValueError):
            validate_flat(self.flat)

    def test_editing_and_deleting_payment_recomputes_the_balance(self):
        payment = repayment_data()
        self.assertEqual(self.summary([payment])["settlements"], [])
        payment["amount_cents"] = 400
        self.assertEqual(self.summary([payment])["settlements"][0]["amount_cents"], 100)
        self.assertEqual(self.summary([])["settlements"][0]["amount_cents"], 500)


class MonthlyBillTests(unittest.TestCase):
    def setUp(self):
        self.flat = household_data()

    def test_templates_create_no_spending_or_debt(self):
        self.flat.update(expenses=[], monthly_bills=[monthly_bill_data()])
        saved = validate_flat(self.flat)
        self.assertEqual(saved["expenses"], [])
        self.assertEqual(summarize_expenses(saved["expenses"], saved["members"])["total_cents"], 0)

    def test_due_day_clamps_to_short_month_and_leap_year(self):
        for today, expected in ((date(2026, 2, 1), "2026-02-28"), (date(2028, 2, 1), "2028-02-29"),
                                (date(2026, 4, 1), "2026-04-30"), (date(2026, 12, 1), "2026-12-31")):
            with self.subTest(today=today):
                self.assertEqual(monthly_bill_status([monthly_bill_data()], [], today)[0]["due_date"], expected)

    def test_recorded_status_is_per_bill_and_calendar_month(self):
        expense = dict(self.flat["expenses"][0], bill_id="internet", bill_month="2026-09")
        status = monthly_bill_status([monthly_bill_data()], [expense], date(2026, 9, 1))
        self.assertEqual(status[0]["expense_id"], "shop")
        self.assertIsNone(monthly_bill_status([monthly_bill_data()], [expense], date(2026, 10, 1))[0]["expense_id"])

    def test_one_bill_cannot_be_recorded_twice_in_the_same_month(self):
        entry = self.flat["expenses"][0]
        entry.update(bill_id="internet", bill_month="2026-09")
        self.flat["expenses"].append(dict(entry, id="duplicate"))
        with self.assertRaisesRegex(ValueError, "already been recorded"):
            validate_flat(self.flat)

    def test_different_months_are_allowed_and_removed_template_keeps_history(self):
        entry = self.flat["expenses"][0]
        entry.update(bill_id="internet", bill_month="2026-09")
        self.flat["expenses"].append(dict(entry, id="october", date="2026-10-01", bill_month="2026-10"))
        self.assertEqual(len(validate_flat(self.flat)["expenses"]), 2)

    def test_bill_period_must_match_the_expense_date(self):
        for change in ({"bill_id": "internet"}, {"bill_month": "2026-09"}, {"bill_id": "internet", "bill_month": "2026-08"}):
            flat = copy.deepcopy(self.flat)
            flat["expenses"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_flat(flat)

    def test_template_validation_and_member_references(self):
        changes = [{"due_day": value} for value in (0, 32, True, 1.5, "1")]
        changes += [{"active": "yes"}, {"paid_by": "missing"}, {"split_between": []}, {"date": "2026-09-30"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_monthly_bill(monthly_bill_data(**change), self.flat["members"])

    def test_duplicate_templates_and_list_limits_are_rejected(self):
        for bills in ([monthly_bill_data(), monthly_bill_data()], [monthly_bill_data(id=str(i)) for i in range(101)]):
            self.flat["monthly_bills"] = bills
            with self.assertRaises(ValueError):
                validate_flat(self.flat)


class ExtendedLedgerStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "test.sqlite3")
        flat = household_data()
        flat.update(repayments=[repayment_data()], monthly_bills=[monthly_bill_data()])
        self.saved = self.storage.save_flat(flat)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_three_round_trip_preserves_ledger_and_templates(self):
        backup = self.storage.export()
        self.assertEqual(backup["schema_version"], 3)
        self.storage.import_data(backup)
        self.assertEqual(self.storage.export(), backup)
        self.assertEqual(self.storage.state()["flat_summary"]["expenses"]["settlements"], [])

    def test_old_open_tab_cannot_silently_drop_new_lists(self):
        self.storage.save_flat(household_data())
        self.assertEqual(self.storage.state()["flat"]["repayments"], self.saved["repayments"])
        self.assertEqual(self.storage.state()["flat"]["monthly_bills"], self.saved["monthly_bills"])

    def test_legacy_backup_restores_only_its_records_and_current_backup_must_be_complete(self):
        backup = self.storage.export()
        legacy = copy.deepcopy(backup)
        legacy["schema_version"] = 2
        legacy["flat"].pop("repayments")
        legacy["flat"].pop("monthly_bills")
        restored = self.storage.import_data(legacy)
        self.assertEqual(restored["flat"]["repayments"], [])
        self.assertEqual(restored["flat"]["monthly_bills"], [])
        legacy["schema_version"] = 3
        before = self.storage.export()
        with self.assertRaises(ValueError):
            self.storage.import_data(legacy)
        self.assertEqual(self.storage.export(), before)

    def test_invalid_payment_import_rolls_back_everything(self):
        before = self.storage.export()
        bad = copy.deepcopy(before)
        bad["room"]["name"] = "Should not replace it"
        bad["flat"]["repayments"][0]["to_id"] = "missing"
        with self.assertRaises(ValueError):
            self.storage.import_data(bad)
        self.assertEqual(self.storage.export(), before)

    def test_repayments_csv_is_separate_and_formula_safe(self):
        flat = copy.deepcopy(self.saved)
        flat["members"][0]["name"] = "=Me"
        flat["repayments"][0]["notes"] = "@formula"
        self.storage.save_flat(flat)
        rows = list(csv.DictReader(io.StringIO(self.storage.export_repayments_csv())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recipient_name"], "'=Me")
        self.assertEqual(rows[0]["notes"], "'@formula")
        self.assertEqual(rows[0]["amount_cents"], "500")


if __name__ == "__main__":
    unittest.main()
