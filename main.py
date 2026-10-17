#!/usr/bin/env python3
"""Vanta language command-line entry point."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compiler.driver import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))