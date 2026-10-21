"""Build hook: put the C++ runtime and shipped Vanta files in the wheel.

The compiler emits `#include "vanta_runtime.hpp"`, `vanta new` points at the
shipped game kit, and `import "std/..."` resolves from the installed standard
library, so all three have to travel with the wheel. Keeping the canonical
copies at the repo root (runtime/, examples/gamekit/, examples/assets/,
stdlib/) means the checkout and the installed package stay the single source
of truth; this hook copies them into the build tree, where setuptools picks
them up as package data.
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
        self._copy_tree(os.path.join(ROOT, 'stdlib'),
                        os.path.join(package, 'templates', 'stdlib'))

    @staticmethod
    def _copy_tree(source, target):
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)


setup(cmdclass={'build_py': build_py})
