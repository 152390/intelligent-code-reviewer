"""Create a TOY dataset in the same formats as the real data, for a dry run of the
training and evaluation scripts. These numbers mean nothing scientifically; they
only prove the scripts work before you spend GPU time on the real datasets.

Writes:
  examples/toy_data/bugs.jsonl         (format of make_bug_samples.py)
  examples/toy_data/reviews.jsonl      (format of CodeReviewer msg-*.jsonl)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "training"))
sys.path.insert(0, os.path.dirname(HERE))
from make_bug_samples import samples_from_pair  # noqa: E402

BUG_PAIRS = [  # (project, file, buggy, fixed, category)
    ("proj_a", "inv/stock.py",
     "def total(items):\n    s = 0\n    for i in range(len(items) + 1):\n        s += items[i]\n    return s\n",
     "def total(items):\n    s = 0\n    for i in range(len(items)):\n        s += items[i]\n    return s\n", "logic"),
    ("proj_a", "inv/users.py",
     "def find(cur, name):\n    cur.execute(f\"SELECT * FROM u WHERE n='{name}'\")\n    return cur.fetchall()\n",
     "def find(cur, name):\n    cur.execute(\"SELECT * FROM u WHERE n=?\", (name,))\n    return cur.fetchall()\n", "security"),
    ("proj_b", "calc/eval.py",
     "def calc(expr):\n    return eval(expr)\n",
     "import ast\n\ndef calc(expr):\n    return ast.literal_eval(expr)\n", "security"),
    ("proj_b", "calc/stats.py",
     "def mean(xs):\n    return sum(xs) / len(xs)\n",
     "def mean(xs):\n    if not xs:\n        return 0.0\n    return sum(xs) / len(xs)\n", "logic"),
    ("proj_c", "app/cache.py",
     "def add(key, store={}):\n    store[key] = True\n    return store\n",
     "def add(key, store=None):\n    store = {} if store is None else store\n    store[key] = True\n    return store\n", "logic"),
    ("proj_c", "app/io.py",
     "def read(p):\n    try:\n        return open(p).read()\n    except:\n        return ''\n",
     "def read(p):\n    try:\n        with open(p) as f:\n            return f.read()\n    except OSError:\n        return ''\n", "quality"),
    ("proj_d", "svc/config.py",
     "API_TOKEN = \"abcd1234efgh\"\n\ndef token():\n    return API_TOKEN\n",
     "import os\n\ndef token():\n    return os.environ['API_TOKEN']\n", "security"),
    ("proj_d", "svc/check.py",
     "def is_empty(x):\n    if x == None:\n        return True\n    return len(x) == 0\n",
     "def is_empty(x):\n    if x is None:\n        return True\n    return len(x) == 0\n", "quality"),
    ("proj_e", "lib/discount.py",
     "def price(p, rate):\n    return p - p * rate * 100\n",
     "def price(p, rate):\n    return p - p * rate\n", "logic"),
    ("proj_e", "lib/sh.py",
     "import subprocess\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n",
     "import subprocess\n\ndef run(cmd):\n    return subprocess.run(cmd.split(), shell=False)\n", "security"),
]

REVIEWS = [
    {"proj": "proj_a", "lang": "py", "msg": "Please use a parameterised query here to avoid SQL injection.",
     "patch": "@@ -1,2 +1,2 @@\n def find(cur, name):\n-    pass\n+    cur.execute(f\"SELECT * FROM u WHERE n='{name}'\")\n",
     "oldf": "def find(cur, name):\n    pass\n"},
    {"proj": "proj_b", "lang": "py", "msg": "LGTM",
     "patch": "@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n", "oldf": "x = 1\n"},
    {"proj": "proj_c", "lang": "py", "msg": "Avoid the mutable default argument; use None instead.",
     "patch": "@@ -1,1 +1,2 @@\n-def add(key):\n+def add(key, store={}):\n+    store[key] = True\n", "oldf": "def add(key):\n    pass\n"},
    {"proj": "proj_e", "lang": "py", "msg": "Use logging instead of print in library code.",
     "patch": "@@ -1,1 +1,2 @@\n def f():\n+    print('debug')\n", "oldf": "def f():\n    pass\n"},
]

if __name__ == "__main__":
    out = os.path.join(HERE, "toy_data")
    os.makedirs(out, exist_ok=True)
    n = 0
    with open(os.path.join(out, "bugs.jsonl"), "w") as f:
        for i, (proj, path, buggy, fixed, cat) in enumerate(BUG_PAIRS):
            for s in samples_from_pair(path, buggy, fixed, proj, f"toy{i}", cat, f"{cat} fault"):
                f.write(json.dumps(s) + "\n")
                n += 1
    with open(os.path.join(out, "reviews.jsonl"), "w") as f:
        for i, r in enumerate(REVIEWS):
            f.write(json.dumps({**r, "id": i}) + "\n")
    print(f"wrote {n} bug samples and {len(REVIEWS)} review samples to {out}")
