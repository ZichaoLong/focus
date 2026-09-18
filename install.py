#!/usr/bin/env python3
"""Public checkout entry point for the shared Focus installer."""

import sys

from bot.installation.installer import main


if __name__ == "__main__":
    main(sys.argv[1:])
