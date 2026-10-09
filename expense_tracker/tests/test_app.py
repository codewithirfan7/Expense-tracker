"""Test cases (run: python -m unittest discover -s tests -v).

TC = test case id, useful for the SE test-plan table in your report.
"""
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app  # noqa: E402


class ExpenseTrackerTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app(self.db_path)
        self.app.config["TESTING"] = True
        self.c = self.app.test_client()
        self.month = date.today().strftime("%Y-%m")
        self.today = date.today().isoformat()

    def tearDown(self):
        os.remove(self.db_path)

    # helpers
    def register(self, u="alice", p="secret1"):
        return self.c.post("/register", data={"username": u, "password": p},
                           follow_redirects=True)

    def login(self, u="alice", p="secret1"):
        return self.c.post("/login", data={"username": u, "password": p},
                           follow_redirects=True)

    def add(self, amount="100", kind="expense", category="Food", tx_date=None,
            note=""):
        return self.c.post("/transactions/add", data={
            "kind": kind, "category": category, "amount": amount,
            "tx_date": tx_date or self.today, "note": note},
            follow_redirects=True)

    def setup_user(self):
        self.register()
        self.login()

    # ---- authentication ----
    def test_tc01_register_and_login(self):
        self.assertIn(b"Account created", self.register().data)
        self.assertIn(b"Hi, alice", self.login().data)

    def test_tc02_duplicate_username_rejected(self):
        self.register()
        self.assertIn(b"already taken", self.register().data)

    def test_tc03_short_password_rejected(self):
        self.assertIn(b"at least 6", self.register(p="123").data)

    def test_tc04_wrong_password_rejected(self):
        self.register()
        self.assertIn(b"Invalid username or password", self.login(p="wrong").data)

    def test_tc05_dashboard_requires_login(self):
        r = self.c.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_tc06_password_is_hashed(self):
        import sqlite3
        self.register()
        row = sqlite3.connect(self.db_path).execute(
            "SELECT password_hash FROM users").fetchone()
        self.assertNotIn("secret1", row[0])

    # ---- transactions ----
    def test_tc07_add_transaction_shows_on_dashboard(self):
        self.setup_user()
        r = self.add(amount="250.50", note="lunch")
        self.assertIn(b"Transaction added", r.data)
        self.assertIn(b"250.50", r.data)
        self.assertIn(b"lunch", r.data)

    def test_tc08_invalid_amount_rejected(self):
        self.setup_user()
        self.assertIn(b"must be a number", self.add(amount="abc").data)
        self.assertIn(b"greater than 0", self.add(amount="-5").data)
        self.assertIn(b"greater than 0", self.add(amount="0").data)

    def test_tc09_invalid_date_rejected(self):
        self.setup_user()
        self.assertIn(b"valid date", self.add(tx_date="2025-13-45").data)

    def test_tc10_invalid_category_rejected(self):
        self.setup_user()
        self.assertIn(b"valid category", self.add(category="Hacking").data)

    def test_tc11_edit_transaction(self):
        self.setup_user()
        self.add(amount="100")
        r = self.c.post("/transactions/1/edit", data={
            "kind": "expense", "category": "Bills", "amount": "175",
            "tx_date": self.today, "note": "edited"}, follow_redirects=True)
        self.assertIn(b"Transaction updated", r.data)
        self.assertIn(b"175.00", r.data)

    def test_tc12_delete_transaction(self):
        self.setup_user()
        self.add(amount="100", note="to-remove")
        r = self.c.post("/transactions/1/delete", follow_redirects=True)
        self.assertIn(b"Transaction deleted", r.data)
        self.assertNotIn(b"to-remove", r.data)

    def test_tc13_cannot_touch_other_users_transaction(self):
        self.setup_user()
        self.add(amount="100", note="alice-private")
        self.c.get("/logout")
        self.register("bob", "secret2")
        self.login("bob", "secret2")
        self.assertIn(b"not found", self.c.post(
            "/transactions/1/delete", follow_redirects=True).data)
        self.assertIn(b"not found", self.c.get(
            "/transactions/1/edit", follow_redirects=True).data)

    # ---- dashboard totals, budget, forecast ----
    def test_tc14_totals_and_balance(self):
        self.setup_user()
        self.add(amount="1000", kind="income", category="Salary")
        self.add(amount="300", kind="expense")
        html = self.c.get(f"/dashboard?month={self.month}").data
        self.assertIn(b"1000.00", html)
        self.assertIn(b"300.00", html)
        self.assertIn(b"700.00", html)

    def test_tc15_budget_exceeded_alert(self):
        self.setup_user()
        self.c.post("/budget", data={"budget": "500"})
        self.add(amount="600")
        self.assertIn(b"Over budget", self.c.get("/dashboard").data)

    def test_tc16_budget_warning_at_80_percent(self):
        self.setup_user()
        self.c.post("/budget", data={"budget": "1000"})
        self.add(amount="850")
        html = self.c.get("/dashboard").data
        self.assertIn(b"85% of your monthly budget", html)
        self.assertNotIn(b"Over budget", html)

    def test_tc17_no_alert_under_budget(self):
        self.setup_user()
        self.c.post("/budget", data={"budget": "1000"})
        self.add(amount="100")
        html = self.c.get("/dashboard").data
        self.assertNotIn(b"Over budget", html)
        self.assertNotIn(b"Careful", html)

    def test_tc18_invalid_budget_rejected(self):
        self.setup_user()
        self.assertIn(b"Budget must be a number",
                      self.c.post("/budget", data={"budget": "-10"},
                                  follow_redirects=True).data)

    def test_tc19_empty_dashboard_does_not_crash(self):
        self.setup_user()
        r = self.c.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No expenses this month", r.data)

    def test_tc20_bad_month_param_falls_back(self):
        self.setup_user()
        self.assertEqual(self.c.get("/dashboard?month=garbage").status_code, 200)

    def test_tc21_forecast_is_average_of_spending_months(self):
        self.setup_user()
        y, m = date.today().year, date.today().month

        def ym_date(delta):
            idx = y * 12 + (m - 1) + delta
            return f"{idx // 12:04d}-{idx % 12 + 1:02d}-15"
        self.add(amount="300", tx_date=ym_date(0))
        self.add(amount="600", tx_date=ym_date(-1))
        # month -2 has no spending, so it is ignored: (300 + 600) / 2 = 450
        self.assertIn(b"450.00", self.c.get("/dashboard").data)


if __name__ == "__main__":
    unittest.main()
