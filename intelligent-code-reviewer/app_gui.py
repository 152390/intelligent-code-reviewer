"""Entry point of the ICR-Reviewer desktop executable."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:                     # allow "ICR-Reviewer review ..." from a terminal too
        from icr.cli import main
        sys.exit(main())
    from icr.gui import main
    main()
