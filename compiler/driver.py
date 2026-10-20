import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from . import VERSION
from .lexer import LexError
from .parser import ParseError
from .loader import load_program, LoadError
from .type_checker import TypeChecker, CheckError
from .codegen_cpp import CodeGen
from .ast_nodes import ExternDecl, FuncDecl


RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'runtime')

# Extern block names that name a library the driver knows how to link. The
# block string is documentation for custom C libraries, but for the libraries
# the game kit uses it is enough information to add the right -l flag.
_AUTO_LIBS = {
    'sdl2': 'SDL2',
    'sdl2_ttf': 'SDL2_ttf',
    'sdl2_image': 'SDL2_image',
}
_AUTO_LIB_ORDER = ('SDL2_image', 'SDL2_ttf', 'SDL2')


def find_cxx_compiler():
    env = os.environ.get('CXX')
    candidates = []
    if env:
        candidates.append(env)
    if os.name == 'nt':
        candidates.extend(['cl', 'clang++', 'g++'])
    else:
        candidates.extend(['clang++', 'g++', 'c++'])
    for c in candidates:
        p = shutil.which(c)
        if p:
            return c, p
    return None, None


def _is_msvc(name):
    base = os.path.basename(name).lower()
    return base in ('cl', 'clang-cl')


def _auto_link_libs(program):
    """Libraries implied by known extern block names, in link order."""
    found = set()
    for decl in program.decls:
        if isinstance(decl, ExternDecl):
            lib = _AUTO_LIBS.get(decl.lib_name.strip().lower())
            if lib is not None:
                found.add(lib)
    return [lib for lib in _AUTO_LIB_ORDER if lib in found]


def _merge_link_libs(program, requested):
    """Add auto-detected libraries after any explicit --link values.

    SDL2 is the base library, so it stays last: add-on libraries such as
    SDL2_ttf and SDL2_image name symbols SDL2 provides.
    """
    libs = list(requested)
    seen = {lib.lower() for lib in libs}
    for lib in _auto_link_libs(program):
        if lib.lower() not in seen:
            libs.append(lib)
            seen.add(lib.lower())
    base = [lib for lib in libs if lib.lower() == 'sdl2']
    if base:
        libs = [lib for lib in libs if lib.lower() != 'sdl2'] + base[:1]
    return libs


def _dedupe_paths(paths):
    out = []
    seen = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _pkg_config_lib_dirs(libs):
    pkg = shutil.which('pkg-config')
    if pkg is None:
        return []
    names = {'SDL2': 'sdl2', 'SDL2_ttf': 'SDL2_ttf', 'SDL2_image': 'SDL2_image'}
    requested = [names[lib] for lib in libs if lib in names]
    if not requested:
        return []
    try:
        proc = subprocess.run([pkg, '--libs-only-L'] + requested,
                              capture_output=True, text=True)
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [token[2:] for token in proc.stdout.split() if token.startswith('-L')]


def _brew_lib_dirs(libs):
    if sys.platform != 'darwin':
        return []
    brew = shutil.which('brew')
    if brew is None:
        return []
    formulas = {'SDL2': 'sdl2', 'SDL2_ttf': 'sdl2_ttf', 'SDL2_image': 'sdl2_image'}
    dirs = []
    for lib in libs:
        formula = formulas.get(lib)
        if formula is None:
            continue
        try:
            proc = subprocess.run([brew, '--prefix', formula],
                                  capture_output=True, text=True)
        except OSError:
            continue
        if proc.returncode == 0:
            dirs.append(os.path.join(proc.stdout.strip(), 'lib'))
    return dirs


def _auto_lib_dirs(libs):
    """Extra -L dirs for libraries outside the default search path."""
    if os.name == 'nt':
        # MinGW's g++ searches its own prefix, where MSYS2 puts SDL2.
        return []
    return _dedupe_paths(
        [d for d in _pkg_config_lib_dirs(libs) + _brew_lib_dirs(libs)
         if os.path.isdir(d)])


def _runtime_env(compiler_path, lib_dirs):
    """On Windows, expose the toolchain and DLLs beside import libraries."""
    if os.name != 'nt':
        return None
    extra = [os.path.dirname(os.path.abspath(compiler_path))]
    for lib_dir in lib_dirs:
        if os.path.basename(lib_dir).lower() == 'lib':
            extra.append(os.path.join(os.path.dirname(lib_dir), 'bin'))
    extra = [d for d in _dedupe_paths(extra) if os.path.isdir(d)]
    if not extra:
        return None
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join(extra + [env.get('PATH', '')])
    return env


def _compiler_cmd(name, path, src, out, release, include_dirs=None, lib_dirs=None, libs=None):
    include_dirs = include_dirs or []
    lib_dirs = lib_dirs or []
    libs = libs or []
    if _is_msvc(name):
        flags = ['/nologo', '/std:c++17', '/EHsc',
                 '/O2' if release else '/Od']
        for d in include_dirs:
            flags.extend(['/I', d])
        flags.extend(['/I', RUNTIME_DIR, src, f'/Fe:{out}'])
        for d in lib_dirs:
            flags.extend(['/LIBPATH:' + d])
        for lib in libs:
            flags.append(lib + '.lib')
        return [path] + flags
    flags = ['-std=c++17', '-Wall', '-Wextra',
             '-O3' if release else '-O0', '-g' if not release else '-g0']
    for d in include_dirs:
        flags.extend(['-I', d])
    flags.extend(['-I', RUNTIME_DIR, src, '-o', out])
    for d in lib_dirs:
        flags.extend(['-L', d])
    for lib in libs:
        flags.extend(['-l', lib])
    return [path] + flags


def _emit_source(program, tc, path):
    cpp = CodeGen(program, tc).generate()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cpp)
    return cpp


def _frontend_only(source_path):
    program = load_program(source_path)
    tc = TypeChecker(program, source_path)
    tc.register()
    tc.check()
    return program, tc


def _report_error(exc):
    sys.stderr.write(str(exc) + '\n')


def cmd_check(args):
    try:
        program, _ = _frontend_only(args.source)
    except (LexError, ParseError, CheckError, LoadError) as e:
        _report_error(e)
        return 1
    if not program.decls:
        sys.stderr.write(f"warning: {args.source} contains no declarations\n")
    print(f"OK: {args.source} type-checks")
    return 0


def cmd_build(args):
    try:
        program, tc = _frontend_only(args.source)
    except (LexError, ParseError, CheckError, LoadError) as e:
        _report_error(e)
        return 1

    if not any(isinstance(d, FuncDecl) and d.name == 'main' for d in program.decls):
        sys.stderr.write(f"error: program has no 'func main() -> void' entry point\n")
        return 1

    name, path = find_cxx_compiler()
    if path is None:
        sys.stderr.write("error: no C++17 compiler found. Install clang++, g++, or cl and retry.\n")
        return 1

    libs = _merge_link_libs(program, args.link)
    lib_dirs = _dedupe_paths(list(args.lib_dir) + _auto_lib_dirs(libs))

    out_path = args.output or os.path.join(
        'build', os.path.splitext(os.path.basename(args.source))[0] +
        ('.exe' if os.name == 'nt' else ''))
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix='vanta_build_')
    cpp_path = os.path.join(tmpdir, 'main.cpp')
    _emit_source(program, tc, cpp_path)

    if args.emit_cpp:
        os.makedirs(os.path.dirname(args.emit_cpp) or '.', exist_ok=True)
        shutil.copyfile(cpp_path, args.emit_cpp)
        print(f"wrote {args.emit_cpp}")

    cmd = _compiler_cmd(name, path, cpp_path, os.path.abspath(out_path), args.release,
                        args.include_dir, lib_dirs, libs)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          env=_runtime_env(path, lib_dirs))
    if proc.returncode != 0:
        sys.stderr.write("error: C++ compilation failed\n")
        sys.stderr.write(proc.stdout + '\n' + proc.stderr + '\n')
        fallback = os.path.join('build', 'vanta_failed.cpp')
        os.makedirs('build', exist_ok=True)
        shutil.copyfile(cpp_path, fallback)
        sys.stderr.write(f"saved generated C++ to {fallback}\n")
        return 1

    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"built {out_path}")
    return 0


def cmd_run(args):
    name, path = find_cxx_compiler()
    if path is None:
        sys.stderr.write("error: no C++17 compiler found\n")
        return 1
    try:
        program, tc = _frontend_only(args.source)
    except (LexError, ParseError, CheckError, LoadError) as e:
        _report_error(e)
        return 1
    if not any(isinstance(d, FuncDecl) and d.name == 'main' for d in program.decls):
        sys.stderr.write("error: program has no main\n")
        return 1

    libs = _merge_link_libs(program, args.link)
    lib_dirs = _dedupe_paths(list(args.lib_dir) + _auto_lib_dirs(libs))
    env = _runtime_env(path, lib_dirs)

    tmpdir = tempfile.mkdtemp(prefix='vanta_run_')
    cpp_path = os.path.join(tmpdir, 'main.cpp')
    _emit_source(program, tc, cpp_path)
    exe = os.path.join(tmpdir, 'prog.exe' if os.name == 'nt' else 'prog')
    cmd = _compiler_cmd(name, path, cpp_path, exe, args.release,
                        args.include_dir, lib_dirs, libs)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        sys.stderr.write("error: C++ compilation failed\n")
        sys.stderr.write(proc.stdout + '\n' + proc.stderr + '\n')
        return 1
    run = subprocess.run([exe] + list(args.prog_args), env=env)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return run.returncode


_COMMANDS = ('check', 'build', 'run')


def _normalize_argv(argv):
    """`vanta game.vnt` is shorthand for `vanta run game.vnt`."""
    argv = list(argv)
    if argv and argv[0] not in _COMMANDS and not argv[0].startswith('-'):
        return ['run'] + argv
    return argv


def main(argv):
    argv = _normalize_argv(argv)
    ap = argparse.ArgumentParser(
        prog='vanta', description='Vanta language compiler',
        epilog='A bare source file runs it: vanta game.vnt')
    ap.add_argument('--version', action='version', version=f'vanta {VERSION}')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_check = sub.add_parser('check', help='type-check a source file')
    p_check.add_argument('source')

    p_build = sub.add_parser('build', help='build a native executable')
    p_build.add_argument('source')
    p_build.add_argument('-o', '--output')
    p_build.add_argument('--release', action='store_true')
    p_build.add_argument('--emit-cpp')
    p_build.add_argument('--include-dir', action='append', default=[],
                         help='add include directory for C++ compilation')
    p_build.add_argument('--lib-dir', action='append', default=[],
                         help='add library directory for linking')
    p_build.add_argument('--link', action='append', default=[],
                         help='link against library (e.g. SDL2)')

    p_run = sub.add_parser('run', help='build and run')
    p_run.add_argument('source')
    p_run.add_argument('--release', action='store_true')
    p_run.add_argument('--include-dir', action='append', default=[],
                       help='add include directory for C++ compilation')
    p_run.add_argument('--lib-dir', action='append', default=[],
                       help='add library directory for linking')
    p_run.add_argument('--link', action='append', default=[],
                       help='link against library (e.g. SDL2)')
    p_run.add_argument('prog_args', nargs='*',
                       help='arguments passed through to the program')

    args = ap.parse_args(argv)
    if args.cmd == 'check':
        return cmd_check(args)
    if args.cmd == 'build':
        return cmd_build(args)
    if args.cmd == 'run':
        return cmd_run(args)
    return 1


def cli():
    """Console-script entry point (the `vanta` command)."""
    return main(sys.argv[1:])
