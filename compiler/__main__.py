"""Support ``python -m compiler lsp`` as a fallback launch path."""
import sys

from .driver import main


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
