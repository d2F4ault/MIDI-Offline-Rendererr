"""Package execution entry point for `python -m pianofall`."""

import sys
from pianofall.cli import main

if __name__ == "__main__":
    sys.exit(main())
