# Expense Tracker

A small web app to track income and expenses, see spending by category, and get budget alerts.
Built with Flask and SQLite (no other dependencies).

## Features
- Register / log in (passwords are hashed)
- Add, edit, delete income and expense transactions
- Monthly dashboard: income, expenses, balance, category pie chart
- Monthly budget with a warning at 80% and an alert when exceeded
- Next-month forecast = average of the last 3 months that had spending

## Run it
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000, register, and log in.
Set a real secret before sharing it: `SECRET_KEY=something-long python app.py`

## Run the tests
```
python -m unittest discover -s tests -v
```
21 test cases (TC01 to TC21) cover auth, validation, ownership checks, totals, budget alerts, and the forecast.

## Project structure
```
app.py            routes, database, validation, forecast
templates/        base, login, register, dashboard, add/edit form
tests/test_app.py automated test cases
```

## Ideas to extend (optional)
- Replace the 3-month average with a scikit-learn LinearRegression forecast
- Export transactions to CSV
- Per-category budgets
