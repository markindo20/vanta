import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import VERSION
from .lexer import LexError
from .parser import ParseError
from .loader import load_program, LoadError, STDLIB_DIR
from .type_checker import TypeChecker, CheckError
from .codegen_cpp import CodeGen
from .ast_nodes import ExternDecl, FuncDecl
from . import ast_nodes as A


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)


def _first_existing_dir(*candidates):
    """Pick the checkout or installed location for a data directory."""
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[-1]


# A wheel installs the runtime, game kit, and assets inside the compiler
# package; a checkout keeps them at the repo root.
RUNTIME_DIR = _first_existing_dir(os.path.join(_HERE, 'runtime'),
                                  os.path.join(_REPO_ROOT, 'runtime'))
_GAMEKIT_DIR = _first_existing_dir(os.path.join(_HERE, 'templates', 'gamekit'),
                                   os.path.join(_REPO_ROOT, 'examples', 'gamekit'))
_ASSETS_DIR = _first_existing_dir(os.path.join(_HERE, 'templates', 'assets'),
                                  os.path.join(_REPO_ROOT, 'examples', 'assets'))

# Extern block names that name a library the driver knows how to link. The
# block string is documentation for custom C libraries, but for the libraries
# the game kit uses it is enough information to add the right -l flag.
_AUTO_LIBS = {
    'sdl2': 'SDL2',
    'sdl2_ttf': 'SDL2_ttf',
    'sdl2_image': 'SDL2_image',
}
_AUTO_LIB_ORDER = ('SDL2_image', 'SDL2_ttf', 'SDL2')

_GAME_TEMPLATE = '''\
# My first Vanta game. Move the paddle with Left/Right (or A/D), catch the
# falling block, and press Esc to quit. The optional argument is a frame
# limit, handy for headless smoke tests:
#
#   vanta game.vnt
#   vanta game.vnt 120
#
# The three imports below are generated relative to this file. The game uses
# only SDL2 core; add gamekit/image.vnt for sprites, text.vnt for a HUD, or
# audio.vnt for sound as you grow it.

import "{{GAMEKIT}}/sdl.vnt"
import "{{GAMEKIT}}/input.vnt"
import "{{GAMEKIT}}/gfx.vnt"

const WIN_W: i32 = 640
const WIN_H: i32 = 480
const PLAYER_W: i32 = 72
const PLAYER_H: i32 = 16
const PLAYER_Y: i32 = 430
const BALL_W: i32 = 24
const BALL_H: i32 = 24
const PLAYER_SPEED: i32 = 7

func ball_x(score: i32) -> i32:
    # A deterministic spread, so a run with no input is reproducible.
    # Import gamekit/rng.vnt when you want a random game.
    return 40 + (score * 97) % 520

func main() -> void:
    let arena = Arena(512)
    let rect = arena.alloc::<i32>(4)
    let ev = arena.alloc::<i32>(14)
    let screen = screen_open("My Vanta Game", WIN_W, WIN_H)
    if not screen_ok(screen):
        print_str("could not open a window")
        screen_close(screen)
        return

    mut player_x = WIN_W / 2 - PLAYER_W / 2
    mut ball_y = 0
    mut score = 0
    mut lives = 3
    mut frames = 0
    mut max_frames = 0
    if arg_count() > 1:
        max_frames = str_to_i32(arg_str(1))

    mut running = true
    while running:
        while SDL_PollEvent(ev) == 1:
            if ev_is_quit(ev):
                running = false
            elif ev_is_keydown(ev):
                let k = ev_key(ev)
                if k == KEY_ESCAPE:
                    running = false
                elif k == KEY_LEFT or k == KEY_A:
                    player_x -= PLAYER_SPEED
                elif k == KEY_RIGHT or k == KEY_D:
                    player_x += PLAYER_SPEED

        player_x = max_i32(0, min_i32(player_x, WIN_W - PLAYER_W))
        ball_y += 4
        let bx = ball_x(score)
        if ball_y + BALL_H >= PLAYER_Y and bx + BALL_W >= player_x and bx <= player_x + PLAYER_W:
            score += 1
            ball_y = 0
        elif ball_y > WIN_H:
            lives -= 1
            ball_y = 0
            if lives <= 0:
                running = false

        gfx_clear(screen, 18, 24, 38)
        gfx_fill_rect(screen, rect, player_x, PLAYER_Y, PLAYER_W, PLAYER_H, 120, 220, 255)
        gfx_fill_rect(screen, rect, bx, ball_y, BALL_W, BALL_H, 255, 210, 90)
        gfx_present(screen)

        frames += 1
        if max_frames > 0 and frames >= max_frames:
            running = false

    screen_close(screen)
    print_fmt("frames {} score {} lives {}", frames, score, lives)
'''


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


def find_debug_compiler():
    """Prefer a DWARF-producing compiler for debug builds.

    The normal driver prefers MSVC on Windows.  GDB cannot read PDB files, so
    debug discovery looks for GCC/Clang first and only falls back to the
    normal choice (which then produces a clear error if it is MSVC).
    """
    env = os.environ.get('CXX')
    candidates = []
    if env:
        candidates.append(env)
    if os.name == 'nt':
        # MinGW GCC reliably emits DWARF.  clang++ on Windows defaults to
        # CodeView, which GDB does not understand, so try g++ first.
        candidates.extend(['g++', 'clang++'])
    else:
        candidates.extend(['clang++', 'g++', 'c++'])
    for candidate in candidates:
        if _is_msvc(candidate):
            continue
        path = shutil.which(candidate)
        if path:
            return candidate, path
    return find_cxx_compiler()


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


def _find_objdump(compiler_path):
    found = shutil.which('objdump')
    if found:
        return found
    candidate = os.path.join(os.path.dirname(os.path.abspath(compiler_path)), 'objdump.exe')
    return candidate if os.path.exists(candidate) else None


def _windows_dll_search_dirs(compiler_path):
    dirs = [os.path.dirname(os.path.abspath(compiler_path))]
    dirs.extend(part for part in os.environ.get('PATH', '').split(os.pathsep) if part)
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    dirs.append(os.path.join(system_root, 'System32'))
    dirs.append(os.path.join(system_root, 'SysWOW64'))
    return _dedupe_paths([d for d in dirs if os.path.isdir(d)])


def _find_case_insensitive(directory, name):
    try:
        for entry in os.listdir(directory):
            if entry.lower() == name.lower():
                return os.path.join(directory, entry)
    except OSError:
        pass
    return None


def _is_windows_system_dll(path):
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    full = os.path.normcase(os.path.abspath(path))
    for name in ('System32', 'SysWOW64'):
        root = os.path.normcase(os.path.join(system_root, name)) + os.sep
        if full.startswith(root):
            return True
    return False


_DLL_NAME_RE = re.compile(r'^\s*DLL Name:\s*(.+?)\s*$', re.IGNORECASE)


def _pe_dll_dependencies(objdump, path):
    try:
        proc = subprocess.run([objdump, '-p', path], capture_output=True, text=True)
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [m.group(1) for line in proc.stdout.splitlines()
            if (m := _DLL_NAME_RE.match(line))]


def _bundle_windows_dlls(exe_path, compiler_path):
    """Copy the executable's non-system DLL dependencies beside it."""
    objdump = _find_objdump(compiler_path)
    out_dir = os.path.dirname(os.path.abspath(exe_path))
    search = _windows_dll_search_dirs(compiler_path)
    copied = []
    missing = []
    seen = set()
    queue = [os.path.abspath(exe_path)]
    while queue:
        binary = queue.pop(0)
        for name in _pe_dll_dependencies(objdump, binary) if objdump else []:
            key = name.lower()
            if key in seen or key.startswith('api-ms-win-') or key.startswith('ext-ms-win-'):
                continue
            seen.add(key)
            found = _find_case_insensitive(out_dir, name)
            if found is None:
                for directory in search:
                    found = _find_case_insensitive(directory, name)
                    if found is not None:
                        break
            if found is None:
                missing.append(name)
                continue
            if _is_windows_system_dll(found):
                continue
            target = os.path.join(out_dir, os.path.basename(found))
            if not os.path.exists(target):
                shutil.copy2(found, target)
                copied.append(os.path.basename(target))
            queue.append(target)
    return copied, missing


def _bundle_repo_assets(out_dir):
    """Copy the shipped example assets, so a bundled example stays runnable."""
    copied = []
    pairs = ((_ASSETS_DIR, os.path.join('examples', 'assets')),
             (os.path.join(_GAMEKIT_DIR, 'fonts'),
              os.path.join('examples', 'gamekit', 'fonts')))
    for source, rel in pairs:
        target = os.path.join(out_dir, rel)
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)
            copied.append(rel)
    return copied


def _link_hint(libs, compiler_name, compiler_path):
    """A platform-specific install hint for missing link libraries."""
    if not libs:
        return None
    if _is_msvc(compiler_name):
        return ("hint: SDL's MinGW import libraries cannot be used with MSVC; "
                "install MSYS2 g++ or link SDL's MSVC .lib files explicitly.")
    if os.name == 'nt':
        compiler_dir = os.path.dirname(os.path.abspath(compiler_path)).lower()
        if 'ucrt64' in compiler_dir:
            env = 'ucrt'
        elif 'clang64' in compiler_dir:
            env = 'clang'
        else:
            env = 'mingw'
        packages = ' '.join(f'mingw-w64-{env}-x86_64-{lib}' for lib in libs)
        return f"hint: install the SDL development packages in MSYS2:\n  pacman -S {packages}"
    if sys.platform == 'darwin':
        formulas = {'SDL2': 'sdl2', 'SDL2_ttf': 'sdl2_ttf', 'SDL2_image': 'sdl2_image'}
        names = ' '.join(formulas.get(lib, lib.lower()) for lib in libs)
        return f"hint: install the SDL development packages:\n  brew install {names}"
    packages = {'SDL2': 'libsdl2-dev', 'SDL2_ttf': 'libsdl2-ttf-dev',
                'SDL2_image': 'libsdl2-image-dev'}
    names = ' '.join(packages.get(lib, lib.lower()) for lib in libs)
    return f"hint: install the SDL development packages:\n  sudo apt-get install {names}"


def _report_compile_failure(proc, libs, compiler_name, compiler_path):
    output = proc.stdout + '\n' + proc.stderr
    sys.stderr.write("error: C++ compilation failed\n")
    sys.stderr.write(output + '\n')
    lower = output.lower()
    missing = [lib for lib in libs
               if f'-l{lib}'.lower() in lower or f'{lib}.lib'.lower() in lower]
    hint = _link_hint(missing, compiler_name, compiler_path)
    if hint:
        sys.stderr.write(hint + '\n')


def _compiler_cmd(name, path, src, out, release, include_dirs=None, lib_dirs=None,
                  libs=None, debug=False):
    include_dirs = include_dirs or []
    lib_dirs = lib_dirs or []
    libs = libs or []
    if _is_msvc(name):
        # /fp:strict keeps f32 arithmetic from contracting into FMA, so the
        # deterministic game runs produce the same counts across targets.
        flags = ['/nologo', '/std:c++17', '/EHsc', '/fp:strict',
                 '/O2' if release and not debug else '/Od']
        if debug:
            flags.extend(['/Zi', '/DEBUG'])
        for d in include_dirs:
            flags.extend(['/I', d])
        flags.extend(['/I', RUNTIME_DIR, src, f'/Fe:{out}'])
        for d in lib_dirs:
            flags.extend(['/LIBPATH:' + d])
        for lib in libs:
            flags.append(lib + '.lib')
        return [path] + flags
    # -ffp-contract=off keeps f32 arithmetic from contracting into FMA, so
    # the deterministic game runs produce the same counts on x86-64 and arm64.
    flags = ['-std=c++17', '-Wall', '-Wextra', '-ffp-contract=off']
    if debug:
        # A debugger needs full DWARF and an unoptimized, frame-pointer-based
        # stack even if the caller also asked for a release build.
        flags.extend(['-O0', '-g3', '-fno-omit-frame-pointer'])
    else:
        flags.extend(['-O3' if release else '-O0', '-g' if not release else '-g0'])
    for d in include_dirs:
        flags.extend(['-I', d])
    flags.extend(['-I', RUNTIME_DIR, src, '-o', out])
    for d in lib_dirs:
        flags.extend(['-L', d])
    for lib in libs:
        flags.extend(['-l', lib])
    return [path] + flags


def _emit_source(program, tc, path, debug=False):
    cpp = CodeGen(program, tc, debug=debug,
                  debug_filename=path if debug else None).generate()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cpp)
    return cpp


def _frontend_only(source_path):
    program = load_program(source_path)
    tc = TypeChecker(program, source_path)
    tc.register()
    tc.check()
    return program, tc


class DebugBuildError(Exception):
    """A debug build failed with a message suitable for a DAP client."""

    def __init__(self, message, output='', tempdir=None):
        super().__init__(message)
        self.message = message
        self.output = output
        self.tempdir = tempdir


def _collect_mutable_names(body, out):
    """Collect the names of mutable local bindings in a statement list."""
    for stmt in body or []:
        if isinstance(stmt, A.VarDecl):
            if stmt.mutable:
                out.add(stmt.name)
        elif isinstance(stmt, A.IfStmt):
            _collect_mutable_names(stmt.then_body, out)
            for branch in stmt.elif_branches or []:
                _collect_mutable_names(branch[1], out)
            _collect_mutable_names(stmt.else_body, out)
        elif isinstance(stmt, A.MatchStmt):
            for arm in stmt.arms or []:
                _collect_mutable_names(arm.body, out)
        elif isinstance(stmt, (A.WhileStmt, A.ForRangeStmt, A.ForEachStmt)):
            _collect_mutable_names(stmt.body, out)


def mutable_locals(program):
    """Map each function to the names of its mutable local bindings.

    The debug adapter uses this to decide whether a variable may be edited:
    Vanta only allows writes to bindings declared with ``mut``.
    """
    result = {}
    for decl in program.decls:
        if isinstance(decl, FuncDecl):
            names = set()
            _collect_mutable_names(decl.body, names)
            result[decl.name] = names
    return result


def program_types(program):
    """Map each user type to its kind (``enum`` or ``struct``)."""
    result = {}
    for decl in program.decls:
        if isinstance(decl, A.EnumDecl):
            result[decl.name] = 'enum'
        elif isinstance(decl, A.StructDecl):
            result[decl.name] = 'struct'
    return result


def program_type_aliases(program):
    """Map each source type name to the internal name the loader gave it."""
    result = {}
    for decl in program.decls:
        if isinstance(decl, (A.EnumDecl, A.StructDecl)):
            source = program.display_names.get(decl.name, decl.name)
            result[source] = decl.name
    return result


def _collect_statement_lines(body, out):
    """Collect the (file, line) of every statement that can hold code."""
    for stmt in body or []:
        pos = getattr(stmt, 'pos', None)
        if pos is not None and pos.file and pos.line:
            out.add((pos.file, pos.line))
        if isinstance(stmt, A.IfStmt):
            _collect_statement_lines(stmt.then_body, out)
            for branch in stmt.elif_branches or []:
                _collect_statement_lines(branch[1], out)
            _collect_statement_lines(stmt.else_body, out)
        elif isinstance(stmt, A.MatchStmt):
            for arm in stmt.arms or []:
                _collect_statement_lines(arm.body, out)
        elif isinstance(stmt, (A.WhileStmt, A.ForRangeStmt, A.ForEachStmt)):
            _collect_statement_lines(stmt.body, out)


def source_lines(program):
    """Map the source files and functions to the lines that hold a statement.

    The debugger uses this to answer breakpoint-location requests and to
    offer jump targets: a line without a statement cannot hold a breakpoint.
    """
    files: dict = {}
    functions: dict = {}
    for decl in program.decls:
        if not isinstance(decl, FuncDecl):
            continue
        lines = set()
        _collect_statement_lines(decl.body, lines)
        per_file: dict = {}
        for file, line in lines:
            key = os.path.normcase(os.path.abspath(file))
            files.setdefault(key, set()).add(line)
            per_file.setdefault(key, set()).add(line)
        functions[decl.name] = {
            key: sorted(value) for key, value in per_file.items()
        }
    return {
        'files': {key: sorted(value) for key, value in files.items()},
        'functions': functions,
    }


def program_layouts(tc):
    """The fields of every struct and the members of every enum.

    The debugger uses this to expand a struct in the Variables view and to
    show the member an enum holds.  The keys are the internal names, which
    are the names the generated C++ uses.
    """
    structs = {}
    for name, st in tc.structs.items():
        if st.builtin and name not in ('Vec2', 'Vec3', 'Quat'):
            continue
        structs[name] = [(field, repr(ftype))
                         for field, ftype in st.fields.items()]
    enums = {}
    for name, et in tc.enums.items():
        if getattr(et, 'has_payloads', False):
            continue
        enums[name] = dict(et.members)
    return {'structs': structs, 'enums': enums}


def build_debug(source, output=None, include_dirs=None, lib_dirs=None,
                link=None):
    """Build an unoptimized executable with Vanta source locations.

    Returns a dictionary with the executable, generated C++, temporary
    directory, and runtime environment.  The caller owns the temporary
    directory and should remove it when the debug session ends.
    """
    try:
        program, tc = _frontend_only(source)
    except (LexError, ParseError, CheckError, LoadError) as e:
        raise DebugBuildError(str(e)) from e

    if not any(isinstance(d, FuncDecl) and d.name == 'main' for d in program.decls):
        raise DebugBuildError("program has no 'func main() -> void' entry point")

    name, path = find_debug_compiler()
    if path is None:
        raise DebugBuildError(
            'no C++17 compiler found; install g++, clang++, or cl and retry')
    if _is_msvc(name):
        raise DebugBuildError(
            'the Vanta debugger currently needs a GCC or Clang toolchain '
            '(MSVC emits PDB files, not the DWARF data GDB reads)')

    libs = _merge_link_libs(program, list(link or []))
    all_lib_dirs = _dedupe_paths(list(lib_dirs or []) + _auto_lib_dirs(libs))
    tmpdir = tempfile.mkdtemp(prefix='vanta_debug_')
    cpp_path = os.path.join(tmpdir, 'main.cpp')
    try:
        _emit_source(program, tc, cpp_path, debug=True)
        if output:
            exe = os.path.abspath(output)
            os.makedirs(os.path.dirname(exe) or '.', exist_ok=True)
        else:
            exe = os.path.join(tmpdir, 'prog.exe' if os.name == 'nt' else 'prog')
        cmd = _compiler_cmd(name, path, cpp_path, exe, release=False,
                            include_dirs=list(include_dirs or []),
                            lib_dirs=all_lib_dirs, libs=libs, debug=True)
        env = _runtime_env(path, all_lib_dirs) or dict(os.environ)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            detail = (proc.stdout + '\n' + proc.stderr).strip()
            raise DebugBuildError('C++ compilation failed', detail, tmpdir)
        # MinGW adds .exe when -o has no suffix.  Report the file that was
        # actually produced so callers do not have to guess.
        if not os.path.exists(exe) and os.name == 'nt' and \
                not exe.lower().endswith('.exe') and os.path.exists(exe + '.exe'):
            exe += '.exe'
        if not os.path.isfile(exe):
            raise DebugBuildError(
                f'C++ compiler reported success but did not create {exe}',
                '', tmpdir)
    except DebugBuildError:
        # Keep the generated source and compiler output for the caller to
        # inspect.  The DAP adapter removes the directory after reporting it.
        raise
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return {
        'exe': exe,
        'cpp': cpp_path,
        'tempdir': tmpdir,
        'env': env,
        'compiler': path,
        'libs': libs,
        'lib_dirs': all_lib_dirs,
        'mutable_locals': mutable_locals(program),
        'types': program_types(program),
        'type_aliases': program_type_aliases(program),
        'source_lines': source_lines(program),
        'layouts': program_layouts(tc),
    }


def _error_location(exc):
    """Return (filename, line, col) for an exception that has a source position."""
    filename = getattr(exc, 'filename', None)
    line = getattr(exc, 'line', None)
    col = getattr(exc, 'col', None)
    if line is None or col is None:
        pos = getattr(exc, 'pos', None)
        if pos is not None:
            filename = getattr(pos, 'file', None) or filename
            line = getattr(pos, 'line', None)
            col = getattr(pos, 'col', None)
    return filename, line, col


def _write_source_context(exc):
    """Show the line and column that a diagnostic points at, when possible."""
    filename, line_no, col_no = _error_location(exc)
    if not filename or line_no is None:
        return
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeError):
        return
    if not (1 <= line_no <= len(lines)):
        return
    source = lines[line_no - 1]
    # Expand tabs so the caret lines up with the printed source text. Vanta
    # rejects tabs in indentation, but a tab could still appear in a string.
    indent = '  '
    caret_col = len(source[:max(0, (col_no or 1) - 1)].expandtabs(4))
    sys.stderr.write(f"{indent}{source.expandtabs(4)}\n")
    sys.stderr.write(f"{indent}{' ' * caret_col}^\n")


def _report_error(exc):
    sys.stderr.write(str(exc) + '\n')
    _write_source_context(exc)


def _gamekit_import(target):
    """The path to the game kit as written in a starter file at `target`."""
    target_dir = os.path.dirname(os.path.abspath(target)) or os.getcwd()
    try:
        path = os.path.relpath(_GAMEKIT_DIR, target_dir)
    except ValueError:
        path = os.path.abspath(_GAMEKIT_DIR)
    return path.replace('\\', '/')


def _starter_source(target):
    return _GAME_TEMPLATE.replace('{{GAMEKIT}}', _gamekit_import(target))


def cmd_new(args):
    target = args.path or 'game.vnt'
    if os.path.exists(target) and not args.force:
        sys.stderr.write(f"error: '{target}' already exists (use --force to replace it)\n")
        return 1
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, 'w', encoding='utf-8', newline='\n') as f:
        f.write(_starter_source(target))
    print(f"created {target}")
    print(f"run it with: vanta {target}")
    return 0


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


def _sdl_lib_found(lib, compiler_path):
    """Best-effort check for an SDL development library (games only)."""
    if compiler_path and os.name == 'nt':
        prefix = os.path.dirname(os.path.dirname(os.path.abspath(compiler_path)))
        libdir = os.path.join(prefix, 'lib')
        names = (f'lib{lib}.dll.a', f'lib{lib}.a', f'{lib}.lib')
        if any(os.path.exists(os.path.join(libdir, n)) for n in names):
            return True
    pkg = {'SDL2': 'sdl2', 'SDL2_ttf': 'SDL2_ttf', 'SDL2_image': 'SDL2_image'}[lib]
    pkg_config = shutil.which('pkg-config')
    if pkg_config:
        try:
            if subprocess.run([pkg_config, '--exists', pkg],
                              capture_output=True).returncode == 0:
                return True
        except OSError:
            pass
    if lib == 'SDL2' and shutil.which('sdl2-config'):
        return True
    dirs = _auto_lib_dirs([lib]) + ['/usr/local/lib', '/opt/homebrew/lib',
                                    '/usr/lib', '/usr/lib/x86_64-linux-gnu']
    for directory in _dedupe_paths([d for d in dirs if os.path.isdir(d)]):
        for ext in ('.so', '.dylib', '.a'):
            if os.path.exists(os.path.join(directory, f'lib{lib}{ext}')):
                return True
    return False


def cmd_doctor(args):
    print(f"vanta {VERSION}")
    print(f"python {sys.version.split()[0]} ({sys.executable})")
    name, path = find_cxx_compiler()
    if path is None:
        sys.stderr.write("error: no C++17 compiler found. Install clang++, g++, or cl and retry.\n")
        return 1
    print(f"c++ compiler: {name} ({path})")
    print(f"runtime header: {os.path.join(RUNTIME_DIR, 'vanta_runtime.hpp')}")
    print(f"game kit: {_GAMEKIT_DIR}")
    print(f"standard library: {STDLIB_DIR or 'not found'}")

    # Compile and run the smallest possible program: this checks the compiler,
    # the include path, and the runtime header in one step.
    tmp = tempfile.mkdtemp(prefix='vanta_doctor_')
    try:
        src = os.path.join(tmp, 'main.cpp')
        with open(src, 'w', encoding='utf-8') as f:
            f.write('#include "vanta_runtime.hpp"\nint main() { return 0; }\n')
        exe = os.path.join(tmp, 'probe.exe' if os.name == 'nt' else 'probe')
        cmd = _compiler_cmd(name, path, src, exe, release=False)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              env=_runtime_env(path, []))
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            sys.stderr.write("error: the C++ compiler could not build a probe program\n")
            return 1
        print("compile test: ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    missing = [lib for lib in ('SDL2', 'SDL2_ttf', 'SDL2_image')
               if not _sdl_lib_found(lib, path)]
    if missing:
        print("SDL2 (games): not detected: " + ', '.join(missing))
        hint = _link_hint(missing, name, path)
        if hint:
            print(hint)
        print("non-game programs are ready; install SDL2 to run the game kit")
    else:
        print("SDL2 (games): found (SDL2, SDL2_ttf, SDL2_image)")
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

    if args.bundle and os.name != 'nt':
        sys.stderr.write("error: --bundle is currently supported on Windows only\n")
        return 1

    libs = _merge_link_libs(program, args.link)
    lib_dirs = _dedupe_paths(list(args.lib_dir) + _auto_lib_dirs(libs))

    stem = os.path.splitext(os.path.basename(args.source))[0]
    filename = stem + ('.exe' if os.name == 'nt' else '')
    if args.output:
        out_path = args.output
    elif args.bundle:
        out_path = os.path.join('build', stem, filename)
    else:
        out_path = os.path.join('build', filename)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix='vanta_build_')
    cpp_path = os.path.join(tmpdir, 'main.cpp')
    _emit_source(program, tc, cpp_path, debug=args.debug)

    if args.emit_cpp:
        os.makedirs(os.path.dirname(args.emit_cpp) or '.', exist_ok=True)
        shutil.copyfile(cpp_path, args.emit_cpp)
        print(f"wrote {args.emit_cpp}")

    cmd = _compiler_cmd(name, path, cpp_path, os.path.abspath(out_path), args.release,
                        args.include_dir, lib_dirs, libs, debug=args.debug)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          env=_runtime_env(path, lib_dirs))
    if proc.returncode != 0:
        _report_compile_failure(proc, libs, name, path)
        fallback = os.path.join('build', 'vanta_failed.cpp')
        os.makedirs('build', exist_ok=True)
        shutil.copyfile(cpp_path, fallback)
        sys.stderr.write(f"saved generated C++ to {fallback}\n")
        return 1

    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"built {out_path}")

    if args.bundle:
        copied, missing = _bundle_windows_dlls(out_path, path)
        if copied:
            print(f"bundled {len(copied)} DLLs beside {out_path}")
        assets = _bundle_repo_assets(os.path.dirname(os.path.abspath(out_path)))
        if assets:
            print("bundled " + ', '.join(assets))
        if _find_objdump(path) is None:
            sys.stderr.write("warning: objdump not found; runtime DLLs were not bundled\n")
        for dep in missing:
            sys.stderr.write(f"warning: dependency not found: {dep}\n")
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
        _report_compile_failure(proc, libs, name, path)
        return 1
    run = subprocess.run([exe] + list(args.prog_args), env=env)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return run.returncode


_COMMANDS = ('new', 'check', 'doctor', 'build', 'run', 'lsp', 'dap')


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

    p_new = sub.add_parser('new', help='create a starter game')
    p_new.add_argument('path', nargs='?', default='game.vnt')
    p_new.add_argument('--force', action='store_true',
                       help='replace an existing file')

    p_check = sub.add_parser('check', help='type-check a source file')
    p_check.add_argument('source')

    sub.add_parser('doctor', help='check the compiler, runtime, and game kit')

    sub.add_parser('lsp', help='run the Vanta language server on stdin/stdout')
    sub.add_parser('dap', help='run the Vanta debug adapter on stdin/stdout')

    p_build = sub.add_parser('build', help='build a native executable')
    p_build.add_argument('source')
    p_build.add_argument('-o', '--output')
    p_build.add_argument('--release', action='store_true')
    p_build.add_argument('--debug', action='store_true',
                         help='emit Vanta source locations for native debugging')
    p_build.add_argument('--bundle', action='store_true',
                         help='copy runtime DLLs and example assets beside the executable (Windows)')
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
    if args.cmd == 'new':
        return cmd_new(args)
    if args.cmd == 'check':
        return cmd_check(args)
    if args.cmd == 'doctor':
        return cmd_doctor(args)
    if args.cmd == 'lsp':
        from .lsp import run_stdio
        return run_stdio()
    if args.cmd == 'dap':
        from .dap import run_stdio
        return run_stdio()
    if args.cmd == 'build':
        return cmd_build(args)
    if args.cmd == 'run':
        return cmd_run(args)
    return 1


def cli():
    """Console-script entry point (the `vanta` command)."""
    return main(sys.argv[1:])
