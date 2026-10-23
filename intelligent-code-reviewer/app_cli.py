"""Entry point of the ICR-Reviewer-cli command-line executable."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from icr.cli import main
    sys.exit(main())
