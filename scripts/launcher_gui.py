"""PyInstaller entry point for the LN-auto desktop app."""

import sys

from window_auto.gui.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
