"""Expense Tracker - a small Flask app (Flask + sqlite3 only).

Run:  python app.py   then open http://127.0.0.1:5000
"""
import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

CATEGORIES = ["Food", "Transport", "Rent", "Shopping", "Bills",
              "Health", "Entertainment", "Education", "Salary", "Other"]


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    app.config["DATABASE"] = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "expenses.db")

    # ---------- database helpers ----------
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                monthly_budget REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
                category TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                tx_date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
        """)
        db.commit()
        db.close()

    init_db()

    # ---------- auth helpers ----------
    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def current_user():
        return get_db().execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    # ---------- validation ----------
    def parse_transaction(form):
        """Return (data, error). Validates amount, date, kind, category."""
        kind = form.get("kind", "")
        category = form.get("category", "")
        note = form.get("note", "").strip()[:200]
        if kind not in ("income", "expense"):
            return None, "Choose income or expense."
        if category not in CATEGORIES:
            return None, "Choose a valid category."
        try:
            amount = float(form.get("amount", ""))
        except ValueError:
            return None, "Amount must be a number."
        if amount <= 0 or amount > 10_000_000:
            return None, "Amount must be greater than 0."
        try:
            tx_date = datetime.strptime(form.get("tx_date", ""), "%Y-%m-%d").date()
        except ValueError:
            return None, "Enter a valid date."
        return {"kind": kind, "category": category, "amount": round(amount, 2),
                "tx_date": tx_date.isoformat(), "note": note}, None

    def month_start(ym):
        return ym + "-01"

    def shift_month(ym, delta):
        y, m = int(ym[:4]), int(ym[5:7])
        idx = y * 12 + (m - 1) + delta
        return f"{idx // 12:04d}-{idx % 12 + 1:02d}"

    def month_expense(user_id, ym):
        row = get_db().execute(
            "SELECT COALESCE(SUM(amount), 0) AS t FROM transactions "
            "WHERE user_id=? AND kind='expense' AND substr(tx_date,1,7)=?",
            (user_id, ym)).fetchone()
        return row["t"]

    def forecast_next_month(user_id, ym):
        """Average expense of the last 3 months that had any spending.

        Simple, explainable forecast (no ML) - see README for how to upgrade.
        """
        totals = [month_expense(user_id, shift_month(ym, -i)) for i in range(3)]
        used = [t for t in totals if t > 0]
        return round(sum(used) / len(used), 2) if used else 0.0

    # ---------- routes: auth ----------
    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if "user_id" in session else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if len(username) < 3:
                flash("Username must be at least 3 characters.", "danger")
            elif len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
            else:
                try:
                    get_db().execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)))
                    get_db().commit()
                    flash("Account created. Please log in.", "success")
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    flash("That username is already taken.", "danger")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?",
                (request.form.get("username", "").strip(),)).fetchone()
            if user and check_password_hash(user["password_hash"],
                                            request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- routes: dashboard ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = current_user()
        ym = request.args.get("month") or date.today().strftime("%Y-%m")
        try:
            datetime.strptime(ym, "%Y-%m")
        except ValueError:
            ym = date.today().strftime("%Y-%m")
        db = get_db()
        rows = db.execute(
            "SELECT * FROM transactions WHERE user_id=? AND substr(tx_date,1,7)=? "
            "ORDER BY tx_date DESC, id DESC", (user["id"], ym)).fetchall()
        income = sum(r["amount"] for r in rows if r["kind"] == "income")
        expense = sum(r["amount"] for r in rows if r["kind"] == "expense")
        by_cat = {}
        for r in rows:
            if r["kind"] == "expense":
                by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
        budget = user["monthly_budget"]
        pct = round(expense / budget * 100) if budget > 0 else None
        return render_template(
            "dashboard.html", user=user, month=ym, rows=rows, income=income,
            expense=expense, balance=income - expense, budget=budget, pct=pct,
            over_budget=budget > 0 and expense > budget,
            near_budget=budget > 0 and 0.8 * budget <= expense <= budget,
            chart_labels=list(by_cat.keys()),
            chart_values=[round(v, 2) for v in by_cat.values()],
            forecast=forecast_next_month(user["id"], ym),
            prev_month=shift_month(ym, -1), next_month=shift_month(ym, 1))

    @app.route("/budget", methods=["POST"])
    @login_required
    def set_budget():
        try:
            value = float(request.form.get("budget", ""))
            if value < 0:
                raise ValueError
        except ValueError:
            flash("Budget must be a number, 0 or more.", "danger")
            return redirect(url_for("dashboard"))
        get_db().execute("UPDATE users SET monthly_budget=? WHERE id=?",
                         (round(value, 2), session["user_id"]))
        get_db().commit()
        flash("Monthly budget updated.", "success")
        return redirect(url_for("dashboard"))

    # ---------- routes: transactions ----------
    @app.route("/transactions/add", methods=["GET", "POST"])
    @login_required
    def add_transaction():
        if request.method == "POST":
            data, err = parse_transaction(request.form)
            if err:
                flash(err, "danger")
            else:
                get_db().execute(
                    "INSERT INTO transactions (user_id, kind, category, amount, "
                    "tx_date, note) VALUES (?, ?, ?, ?, ?, ?)",
                    (session["user_id"], data["kind"], data["category"],
                     data["amount"], data["tx_date"], data["note"]))
                get_db().commit()
                flash("Transaction added.", "success")
                return redirect(url_for("dashboard", month=data["tx_date"][:7]))
        return render_template("form.html", tx=None, categories=CATEGORIES,
                               today=date.today().isoformat())

    def get_own_tx(tx_id):
        return get_db().execute(
            "SELECT * FROM transactions WHERE id=? AND user_id=?",
            (tx_id, session["user_id"])).fetchone()

    @app.route("/transactions/<int:tx_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_transaction(tx_id):
        tx = get_own_tx(tx_id)
        if tx is None:
            flash("Transaction not found.", "danger")
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            data, err = parse_transaction(request.form)
            if err:
                flash(err, "danger")
            else:
                get_db().execute(
                    "UPDATE transactions SET kind=?, category=?, amount=?, "
                    "tx_date=?, note=? WHERE id=? AND user_id=?",
                    (data["kind"], data["category"], data["amount"],
                     data["tx_date"], data["note"], tx_id, session["user_id"]))
                get_db().commit()
                flash("Transaction updated.", "success")
                return redirect(url_for("dashboard", month=data["tx_date"][:7]))
        return render_template("form.html", tx=tx, categories=CATEGORIES,
                               today=date.today().isoformat())

    @app.route("/transactions/<int:tx_id>/delete", methods=["POST"])
    @login_required
    def delete_transaction(tx_id):
        tx = get_own_tx(tx_id)
        if tx is None:
            flash("Transaction not found.", "danger")
            return redirect(url_for("dashboard"))
        get_db().execute("DELETE FROM transactions WHERE id=? AND user_id=?",
                         (tx_id, session["user_id"]))
        get_db().commit()
        flash("Transaction deleted.", "success")
        return redirect(url_for("dashboard", month=tx["tx_date"][:7]))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
    
    