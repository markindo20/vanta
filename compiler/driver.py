import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from . import VERSION
from .lexer import Lexer, LexError
from .parser import Parser, ParseError
from .type_checker import TypeChecker, CheckError
from .codegen_cpp import CodeGen
from .ast_nodes import FuncDecl


RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'runtime')


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


def _compiler_cmd(name, path, src, out, release):
    if _is_msvc(name):
        flags = ['/nologo', '/std:c++17', '/EHsc',
                 '/O2' if release else '/Od', '/I', RUNTIME_DIR,
                 src, f'/Fe:{out}']
        return [path] + flags
    flags = ['-std=c++17', '-Wall', '-Wextra',
             '-O3' if release else '-O0', '-g' if not release else '-g0',
             '-I', RUNTIME_DIR, src, '-o', out]
    return [path] + flags


def _emit_source(program, tc, path):
    cpp = CodeGen(program, tc).generate()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cpp)
    return cpp


def _frontend_only(source_path):
    with open(source_path, 'r', encoding='utf-8') as f:
        src = f.read()
    tokens = Lexer(src, source_path).tokenize()
    program = Parser(tokens, source_path).parse_program()
    tc = TypeChecker(program, source_path)
    tc.register()
    tc.check()
    return program, tc


def _report_error(exc):
    sys.stderr.write(str(exc) + '\n')


def cmd_check(args):
    try:
        program, _ = _frontend_only(args.source)
    except (LexError, ParseError, CheckError) as e:
        _report_error(e)
        return 1
    if not program.decls:
        sys.stderr.write(f"warning: {args.source} contains no declarations\n")
    print(f"OK: {args.source} type-checks")
    return 0


def cmd_build(args):
    try:
        program, tc = _frontend_only(args.source)
    except (LexError, ParseError, CheckError) as e:
        _report_error(e)
        return 1

    if not any(isinstance(d, FuncDecl) and d.name == 'main' for d in program.decls):
        sys.stderr.write(f"error: program has no 'func main() -> void' entry point\n")
        return 1

    name, path = find_cxx_compiler()
    if path is None:
        sys.stderr.write("error: no C++17 compiler found. Install clang++, g++, or cl and retry.\n")
        return 1

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

    cmd = _compiler_cmd(name, path, cpp_path, os.path.abspath(out_path), args.release)
    proc = subprocess.run(cmd, capture_output=True, text=True)
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
    except (LexError, ParseError, CheckError) as e:
        _report_error(e)
        return 1
    if not any(isinstance(d, FuncDecl) and d.name == 'main' for d in program.decls):
        sys.stderr.write("error: program has no main\n")
        return 1
    tmpdir = tempfile.mkdtemp(prefix='vanta_run_')
    cpp_path = os.path.join(tmpdir, 'main.cpp')
    _emit_source(program, tc, cpp_path)
    exe = os.path.join(tmpdir, 'prog.exe' if os.name == 'nt' else 'prog')
    cmd = _compiler_cmd(name, path, cpp_path, exe, args.release)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write("error: C++ compilation failed\n")
        sys.stderr.write(proc.stdout + '\n' + proc.stderr + '\n')
        return 1
    run = subprocess.run([exe] + list(args.prog_args))
    shutil.rmtree(tmpdir, ignore_errors=True)
    return run.returncode


def main(argv):
    ap = argparse.ArgumentParser(prog='vanta', description='Vanta language compiler')
    ap.add_argument('--version', action='version', version=f'vanta {VERSION}')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_check = sub.add_parser('check', help='type-check a source file')
    p_check.add_argument('source')

    p_build = sub.add_parser('build', help='build a native executable')
    p_build.add_argument('source')
    p_build.add_argument('-o', '--output')
    p_build.add_argument('--release', action='store_true')
    p_build.add_argument('--emit-cpp')

    p_run = sub.add_parser('run', help='build and run')
    p_run.add_argument('source')
    p_run.add_argument('--release', action='store_true')
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