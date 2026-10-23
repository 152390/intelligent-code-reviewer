"""Create examples/demo_repo (see icr/demo.py for what it contains)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from icr.demo import create_demo_repo  # noqa: E402

if __name__ == "__main__":
    root = create_demo_repo(os.path.join(HERE, "demo_repo"))
    print(f"Demo repository created at {root}")
    print("Review it with:\n  python -m icr review --repo examples/demo_repo --base HEAD~1 --backend heuristic")
