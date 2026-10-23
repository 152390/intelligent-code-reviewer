"""Create examples/demo_repo: a tiny shop project with two commits.

Commit 1 (base): clean code.
Commit 2 (the "pull request"): adds features containing planted problems:
  logic     off-by-one loop, None returned by get_price() used in arithmetic (needs
            repository context: get_price is defined in another file), mutable default
            argument, division by len() of a possibly empty list
  security  SQL injection, eval on input, hard-coded API key
  quality   bare except, '== None'
  noise     print(), magic number, TODO, missing docstring (should be filtered or low priority)
  clean     is_known() in utils.py is correct and should receive no findings

Create it from the app (button "Create demo project") or the command line:
  ICR-Reviewer-cli demo --path demo_repo
"""
import os
import shutil
import subprocess


BASE = {
    "shop/__init__.py": "",
    "shop/utils.py": '''"""Helper functions for the shop."""

PRICES = {"apple": 120, "bread": 850, "milk": 600}


def get_price(item):
    """Return the price of an item in naira, or None if the item is unknown."""
    if item in PRICES:
        return PRICES[item]
    return None


def format_naira(amount):
    """Format an amount as a naira string."""
    return f"N{amount:,.2f}"
''',
    "shop/cart.py": '''"""Shopping cart."""
from shop.utils import get_price, format_naira


class Cart:
    """A simple shopping cart."""

    def __init__(self):
        self.items = []

    def add(self, item):
        """Add an item to the cart."""
        self.items.append(item)
''',
    "shop/db.py": '''"""Database access."""
import sqlite3


def connect(path="shop.db"):
    """Open a database connection."""
    return sqlite3.connect(path)
''',
    "CONTRIBUTING.md": '''# Contributing guidelines

- Database queries must use parameterised queries, never string formatting.
- Use the logging module, not print, for diagnostics.
- Never commit secrets or API keys; read them from environment variables.
- Compare with None using `is None`.
- Catch specific exceptions; bare except is not allowed.
''',
}

PR_CHANGES = {
    "shop/cart.py": BASE["shop/cart.py"] + '''
    def total(self):
        """Return the total price of the cart."""
        total = 0
        for i in range(len(self.items) + 1):
            total += get_price(self.items[i])
        return total

    def average_price(self):
        return self.total() / len(self.items)

    def apply_discount(self, code, history=[]):
        history.append(code)
        if code == None:
            return self.total()
        return self.total() * 0.925

    def receipt(self):
        """Return the formatted total."""
        print("Generating receipt")
        try:
            return format_naira(self.total())
        except:
            return "error"
''',
    "shop/db.py": BASE["shop/db.py"].replace('import sqlite3\n', 'import sqlite3\n\nAPI_KEY = "sk-live-9f8a7b6c5d4e"\n') + '''

def find_user(conn, name):
    """Find users by name."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM users WHERE name = '{name}'")
    return cursor.fetchall()


def run_report(expr):
    """Evaluate a report expression."""
    # TODO: replace with a proper parser
    return eval(expr)
''',
    "shop/utils.py": BASE["shop/utils.py"] + '''

def is_known(item):
    """Return True if the item has a price."""
    return item in PRICES
''',
}


def write(root, files):
    for path, text in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def create_demo_repo(root: str) -> str:
    """Create the demo project at `root` (replacing it if it exists). Needs Git."""
    if not shutil.which("git"):
        raise RuntimeError("Git is not installed or not on PATH. Install Git from https://git-scm.com/downloads")
    root = os.path.abspath(root)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)

    def git(*args):
        subprocess.run(["git", "-C", root, *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "demo@example.com")
    git("config", "user.name", "Demo")
    git("config", "commit.gpgsign", "false")
    write(root, BASE)
    git("add", ".")
    git("commit", "-q", "-m", "Base shop project")
    write(root, PR_CHANGES)
    git("add", ".")
    git("commit", "-q", "-m", "Add cart totals, discounts, receipts and user lookup")
    return root
