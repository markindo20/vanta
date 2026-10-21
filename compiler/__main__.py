"""Support ``python -m compiler <command>``, including lsp and dap fallbacks."""
import sys

from .driver import main


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
