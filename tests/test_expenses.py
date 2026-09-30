import copy
import math
import random
import unittest

from roommate.expenses import expense_shares, summarize_expenses, validate_expense
from roommate.geometry import ValidationError


class ExpenseTests(unittest.TestCase):
    def setUp(self):
        self.members = [
            {"id": "alice", "name": "Alice"},
            {"id": "ben", "name": "Ben"},
            {"id": "cara", "name": "Cara"},
        ]
        self.expense = {
            "id": "groceries-1", "title": "Weekly groceries", "amount_cents": 2000,
            "paid_by": "alice", "split_between": ["alice", "ben", "cara"],
            "date": "2026-09-30", "category": "groceries", "notes": "Shared shelf only",
        }

    def ledger(self, expenses=None, members=None):
        return summarize_expenses(
            [self.expense] if expenses is None else expenses,
            self.members if members is None else members,
        )

    def test_twenty_euros_split_three_ways_keeps_every_cent(self):
        result = self.ledger()
        self.assertEqual(expense_shares(self.expense), {"alice": 667, "ben": 667, "cara": 666})
        self.assertEqual(result["total_cents"], 2000)
        self.assertEqual(result["balances"], [
            {"member_id": "alice", "name": "Alice", "paid_cents": 2000, "share_cents": 667, "balance_cents": 1333},
            {"member_id": "ben", "name": "Ben", "paid_cents": 0, "share_cents": 667, "balance_cents": -667},
            {"member_id": "cara", "name": "Cara", "paid_cents": 0, "share_cents": 666, "balance_cents": -666},
        ])
        self.assertEqual(result["settlements"], [
            {"from_id": "ben", "to_id": "alice", "amount_cents": 667},
            {"from_id": "cara", "to_id": "alice", "amount_cents": 666},
        ])

    def test_one_cent_can_be_shared_without_negative_or_fractional_shares(self):
        self.expense.update(amount_cents=1, paid_by="cara")
        result = self.ledger()
        self.assertEqual(expense_shares(self.expense), {"alice": 1, "ben": 0, "cara": 0})
        self.assertEqual(result["settlements"], [{"from_id": "alice", "to_id": "cara", "amount_cents": 1}])

    def test_remainder_follows_the_saved_participant_order(self):
        self.expense.update(amount_cents=2, split_between=["cara", "alice", "ben"])
        self.assertEqual(list(expense_shares(self.expense).items()), [("cara", 1), ("alice", 1), ("ben", 0)])

    def test_member_can_pay_for_others_without_taking_a_share(self):
        self.expense.update(amount_cents=1000, split_between=["ben", "cara"])
        result = self.ledger()
        self.assertEqual([entry["balance_cents"] for entry in result["balances"]], [1000, -500, -500])
        self.assertEqual(result["settlements"], [
            {"from_id": "ben", "to_id": "alice", "amount_cents": 500},
            {"from_id": "cara", "to_id": "alice", "amount_cents": 500},
        ])

    def test_balanced_bills_need_no_transfer(self):
        first = {**self.expense, "amount_cents": 1200, "split_between": ["alice", "ben"]}
        second = {**first, "id": "cleaning-1", "title": "Cleaning supplies", "paid_by": "ben"}
        result = self.ledger([first, second])
        self.assertEqual(result["total_cents"], 2400)
        self.assertEqual([entry["balance_cents"] for entry in result["balances"]], [0, 0, 0])
        self.assertEqual(result["settlements"], [])

    def test_no_expenses_still_shows_every_member(self):
        result = self.ledger([])
        self.assertEqual(result["total_cents"], 0)
        self.assertEqual([entry["member_id"] for entry in result["balances"]], ["alice", "ben", "cara"])
        self.assertTrue(all(entry["paid_cents"] == entry["share_cents"] == entry["balance_cents"] == 0
                            for entry in result["balances"]))
        self.assertEqual(result["settlements"], [])

    def test_normalization_is_detached_and_does_not_change_the_receipt(self):
        original = copy.deepcopy(self.expense)
        self.expense["title"] = "  Weekly groceries  "
        self.expense.pop("notes")
        self.expense.pop("category")
        clean = validate_expense(self.expense, self.members)
        self.assertEqual(clean["title"], "Weekly groceries")
        self.assertEqual(clean["notes"], "")
        self.assertEqual(clean["category"], "other")
        clean["split_between"].append("new-member")
        self.assertEqual(self.expense["split_between"], original["split_between"])
        self.assertEqual(self.expense["title"], "  Weekly groceries  ")

    def test_unknown_fields_are_rejected_instead_of_disappearing(self):
        for field in ("amount_eur", "paid", 5):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_expense({**self.expense, field: 1}, self.members)

    def test_invalid_money_never_enters_the_ledger(self):
        for amount in (0, -1, True, False, 1.0, 19.99, math.inf, math.nan,
                       "2000", None, 100_000_001):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.ledger([{**self.expense, "amount_cents": amount}])
        missing = {key: value for key, value in self.expense.items() if key != "amount_cents"}
        with self.assertRaises(ValidationError):
            validate_expense(missing, self.members)

    def test_participants_must_be_unique_current_member_ids(self):
        for participants in ([], ["alice", "alice"], ["missing"], "alice",
                             ("alice",), [True], [" alice"], ["alice"] * 21):
            with self.subTest(participants=participants), self.assertRaises(ValidationError):
                validate_expense({**self.expense, "split_between": participants}, self.members)

    def test_removing_a_payer_or_participant_cannot_reassign_history(self):
        for removed in ("alice", "ben"):
            members = [member for member in self.members if member["id"] != removed]
            with self.subTest(removed=removed), self.assertRaises(ValidationError):
                self.ledger(members=members)
        self.expense["paid_by"] = "missing"
        with self.assertRaises(ValidationError):
            validate_expense(self.expense, self.members)

    def test_dates_must_be_real_and_use_the_visible_calendar_format(self):
        for expense_date in ("2026-02-29", "2026-09-31", "2026-9-30", "20260930",
                             "2026-09-30T10:30:00Z", "0000-01-01", True, None):
            with self.subTest(date=expense_date), self.assertRaises(ValidationError):
                validate_expense({**self.expense, "date": expense_date}, self.members)
        leap_day = validate_expense({**self.expense, "date": "2028-02-29"}, self.members)
        self.assertEqual(leap_day["date"], "2028-02-29")

    def test_required_labels_ids_and_categories_have_clear_limits(self):
        cases = [
            {"id": ""}, {"id": "expense/1"}, {"id": "e" * 65},
            {"title": "   "}, {"title": "t" * 121}, {"title": None},
            {"notes": "n" * 2001}, {"notes": False},
            {"category": "shopping"}, {"category": ["groceries"]},
        ]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                validate_expense({**self.expense, **fields}, self.members)

    def test_duplicate_receipts_cannot_double_the_total(self):
        with self.assertRaises(ValidationError):
            self.ledger([self.expense, copy.deepcopy(self.expense)])

    def test_malformed_members_and_expense_collections_are_rejected(self):
        bad_members = [
            [], {}, [None], [{"id": "alice", "name": ""}],
            [{"id": "alice", "name": "Alice"}] * 2,
            [{"id": str(index), "name": "Member"} for index in range(21)],
        ]
        for members in bad_members:
            with self.subTest(members=members), self.assertRaises(ValidationError):
                summarize_expenses([], members)
        for expenses in (None, {}, "receipt", [None]):
            with self.subTest(expenses=expenses), self.assertRaises(ValidationError):
                summarize_expenses(expenses, self.members)

    def test_maximum_size_ledger_remains_exact_and_rejects_the_next_receipt(self):
        members = [{"id": f"member-{index}", "name": f"Member {index}"} for index in range(20)]
        expenses = [{
            **self.expense, "id": f"expense-{index}", "amount_cents": 100_000_000,
            "paid_by": members[index % 20]["id"],
            "split_between": [member["id"] for member in members],
        } for index in range(500)]
        result = self.ledger(expenses, members)
        self.assertEqual(result["total_cents"], 50_000_000_000)
        self.assertEqual(result["settlements"], [])
        with self.assertRaises(ValidationError):
            self.ledger(expenses + [{**expenses[0], "id": "expense-500"}], members)

    def test_varied_ledgers_reconcile_after_the_suggested_transfers(self):
        randomizer = random.Random(43)
        for member_count in range(2, 21):
            members = [{"id": f"m-{index}", "name": f"Member {index}"} for index in range(member_count)]
            identities = [member["id"] for member in members]
            expenses = [{
                **self.expense, "id": f"bill-{index}",
                "amount_cents": randomizer.randint(1, 100_000),
                "paid_by": randomizer.choice(identities),
                "split_between": randomizer.sample(identities, randomizer.randint(1, member_count)),
            } for index in range(35)]
            result = self.ledger(expenses, members)
            with self.subTest(member_count=member_count):
                self.assertEqual(sum(entry["paid_cents"] for entry in result["balances"]), result["total_cents"])
                self.assertEqual(sum(entry["share_cents"] for entry in result["balances"]), result["total_cents"])
                remaining = {entry["member_id"]: entry["balance_cents"] for entry in result["balances"]}
                self.assertEqual(sum(remaining.values()), 0)
                self.assertLessEqual(len(result["settlements"]), member_count - 1)
                for transfer in result["settlements"]:
                    self.assertIs(type(transfer["amount_cents"]), int)
                    self.assertGreater(transfer["amount_cents"], 0)
                    self.assertNotEqual(transfer["from_id"], transfer["to_id"])
                    remaining[transfer["from_id"]] += transfer["amount_cents"]
                    remaining[transfer["to_id"]] -= transfer["amount_cents"]
                self.assertTrue(all(amount == 0 for amount in remaining.values()))
                self.assertEqual(self.ledger(list(reversed(expenses)), members), result)

    def test_calculating_the_summary_preserves_saved_input(self):
        expenses, members = [copy.deepcopy(self.expense)], copy.deepcopy(self.members)
        before = copy.deepcopy((expenses, members))
        self.ledger(expenses, members)
        self.assertEqual((expenses, members), before)


if __name__ == "__main__":
    unittest.main()
