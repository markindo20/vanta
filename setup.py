"""Build hook: put the C++ runtime and game kit inside the installed package.

The compiler emits `#include "vanta_runtime.hpp"` and `vanta new` points at
the shipped game kit, so both have to travel with the wheel. Keeping the
canonical copies at the repo root (runtime/, examples/gamekit/) means the
checkout and the examples stay the single source of truth; this hook copies
them into the build tree, where setuptools picks them up as package data.
"""
import os
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

ROOT = os.path.dirname(os.path.abspath(__file__))


class build_py(_build_py):
    def run(self):
        super().run()
        package = os.path.join(self.build_lib, 'compiler')
        self._copy_tree(os.path.join(ROOT, 'runtime'),
                        os.path.join(package, 'runtime'))
        self._copy_tree(os.path.join(ROOT, 'examples', 'gamekit'),
                        os.path.join(package, 'templates', 'gamekit'))
        self._copy_tree(os.path.join(ROOT, 'examples', 'assets'),
                        os.path.join(package, 'templates', 'assets'))

    @staticmethod
    def _copy_tree(source, target):
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)


setup(cmdclass={'build_py': build_py})
