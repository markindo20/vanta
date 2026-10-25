import os
import shutil
import tempfile
import textwrap
import unittest

from compiler.loader import load_program, LoadError
from compiler.type_checker import TypeChecker, CheckError


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='vanta_mod_')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, source):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(textwrap.dedent(source).lstrip('\n'))
        return path

    def check(self, name='main.vnt'):
        path = os.path.join(self.dir, name)
        program = load_program(path)
        tc = TypeChecker(program, path)
        tc.register()
        tc.check()
        return program, tc

    def test_qualified_import_exposes_only_public_names(self):
        self.write('geometry.vnt', '''
            module geometry

            pub const ORIGIN_X: i32 = 3

            func square(n: i32) -> i32:
                return n * n

            pub struct Point:
                pub x: i32
                pub y: i32

            pub enum Shape:
                Dot
                Square(i32)

            pub func length_squared(p: Point) -> i32:
                return square(p.x) + square(p.y)

            pub func area(shape: Shape) -> i32:
                match shape:
                    Shape.Dot:
                        return 0
                    Shape.Square(side):
                        return square(side)
        ''')
        self.write('main.vnt', '''
            import "geometry.vnt" as geo

            func main() -> void:
                let p = geo.Point(x: 3, y: 4)
                print_i32(geo.length_squared(p))
                print_i32(geo.area(geo.Shape.Square(5)))
                print_i32(geo.ORIGIN_X)
        ''')
        _program, tc = self.check()
        self.assertIn('vanta_m_geometry__length_squared', tc.functions)
        self.assertIn('vanta_m_geometry__square', tc.functions)
        self.assertIn('main', tc.functions)

    def test_private_symbol_is_not_visible(self):
        self.write('geometry.vnt', '''
            module geometry

            func hidden() -> i32:
                return 7
        ''')
        self.write('main.vnt', '''
            import "geometry.vnt" as geo

            func main() -> void:
                print_i32(geo.hidden())
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("symbol 'hidden' is private", str(cm.exception))

    def test_unaliased_import_exposes_public_names(self):
        self.write('math.vnt', '''
            module math

            pub func add(a: i32, b: i32) -> i32:
                return a + b
        ''')
        self.write('main.vnt', '''
            import "math.vnt"

            func main() -> void:
                print_i32(add(2, 3))
        ''')
        _program, tc = self.check()
        self.assertIn('vanta_m_math__add', tc.functions)

    def test_same_names_in_two_modules(self):
        self.write('alpha.vnt', '''
            module alpha

            pub struct Color:
                pub r: i32

            pub func value() -> i32:
                return 10
        ''')
        self.write('beta.vnt', '''
            module beta

            pub struct Color:
                pub b: i32

            pub func value() -> i32:
                return 20
        ''')
        self.write('main.vnt', '''
            import "alpha.vnt" as a
            import "beta.vnt" as b

            func main() -> void:
                let ca = a.Color(r: 1)
                let cb = b.Color(b: 2)
                print_i32(a.value() + b.value())
                print_i32(ca.r + cb.b)
        ''')
        _program, tc = self.check()
        self.assertIn('vanta_m_alpha__Color', tc.structs)
        self.assertIn('vanta_m_beta__Color', tc.structs)

    def test_legacy_flat_import_still_works(self):
        self.write('legacy_lib.vnt', '''
            struct Sprite:
                pub pixel: i32

            func sprite_at(pixel: i32) -> Sprite:
                return Sprite(pixel: pixel)
        ''')
        self.write('main.vnt', '''
            import "legacy_lib.vnt"

            func main() -> void:
                let s = sprite_at(4)
                print_i32(s.pixel)
        ''')
        _program, tc = self.check()
        self.assertIn('sprite_at', tc.functions)
        self.assertIn('Sprite', tc.structs)

    def test_duplicate_module_name_is_an_error(self):
        self.write('one.vnt', '''
            module shared

            pub func one() -> i32:
                return 1
        ''')
        self.write('two.vnt', '''
            module shared

            pub func two() -> i32:
                return 2
        ''')
        self.write('main.vnt', '''
            import "one.vnt" as one
            import "two.vnt" as two

            func main() -> void:
                print_i32(one.one() + two.two())
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("module 'shared' is already defined", str(cm.exception))

    def test_module_declaration_must_be_first(self):
        self.write('main.vnt', '''
            import "lib.vnt"
            module late

            func main() -> void:
                print_i32(1)
        ''')
        self.write('lib.vnt', '''
            module lib

            pub func value() -> i32:
                return 1
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn('module declaration must be the first', str(cm.exception))

    def test_ambiguous_unqualified_import(self):
        self.write('a.vnt', '''
            module a

            pub func value() -> i32:
                return 1
        ''')
        self.write('b.vnt', '''
            module b

            pub func value() -> i32:
                return 2
        ''')
        self.write('main.vnt', '''
            import "a.vnt"
            import "b.vnt"

            func main() -> void:
                print_i32(value())
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("ambiguous name 'value'", str(cm.exception))

    def test_qualified_match_pattern(self):
        self.write('shapes.vnt', '''
            module shapes

            pub enum Shape:
                Dot
                Square(i32)

            pub func area(shape: Shape) -> i32:
                match shape:
                    Shape.Dot:
                        return 0
                    Shape.Square(side):
                        return side * side
        ''')
        self.write('main.vnt', '''
            import "shapes.vnt" as shapes

            func main() -> void:
                print_i32(shapes.area(shapes.Shape.Square(4)))
        ''')
        _program, tc = self.check()
        self.assertIn('vanta_m_shapes__area', tc.functions)

    def test_local_variable_shadows_module_alias(self):
        self.write('geometry.vnt', '''
            module geometry

            pub struct Point:
                x: i32
                y: i32
        ''')
        self.write('main.vnt', '''
            import "geometry.vnt" as geo

            struct Point:
                pub x: i32
                pub y: i32

            func main() -> void:
                let geo = Point(x: 1, y: 2)
                print_i32(geo.x)
        ''')
        self.check()

    def test_entry_module_main_is_entry_point(self):
        self.write('main.vnt', '''
            module app

            func helper() -> i32:
                return 41

            func main() -> void:
                print_i32(helper() + 1)
        ''')
        _program, tc = self.check()
        self.assertIn('main', tc.functions)
        self.assertIn('vanta_m_app__helper', tc.functions)

    def test_public_extern_in_module(self):
        self.write('cbits.vnt', '''
            module cbits

            pub extern "c" {
                func abs(x: i32) -> i32
            }
        ''')
        self.write('main.vnt', '''
            import "cbits.vnt" as cbits

            func main() -> void:
                print_i32(cbits.abs(-4))
        ''')
        _program, tc = self.check()
        self.assertTrue(tc.functions['abs'].is_extern)

    def test_legacy_import_collision_is_an_error(self):
        self.write('one.vnt', '''
            func value() -> i32:
                return 1
        ''')
        self.write('two.vnt', '''
            func value() -> i32:
                return 2
        ''')
        self.write('main.vnt', '''
            import "one.vnt"
            import "two.vnt"

            func main() -> void:
                print_i32(value())
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("imported name 'value' is declared in multiple files",
                      str(cm.exception))

    def test_public_function_cannot_expose_private_type(self):
        self.write('secret.vnt', '''
            module secret

            struct Hidden:
                x: i32

            pub func make() -> Hidden:
                return Hidden(x: 1)
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                let value = secret.make()
                print_i32(value.x)
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("exposes private type 'Hidden'", str(cm.exception))

    def test_public_struct_cannot_expose_private_type(self):
        self.write('secret.vnt', '''
            module secret

            struct Hidden:
                x: i32

            pub struct Box:
                value: Hidden
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                print_i32(1)
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("exposes private type 'Hidden'", str(cm.exception))

    def test_legacy_import_is_still_transitive(self):
        self.write('base.vnt', '''
            func base_value() -> i32:
                return 5
        ''')
        self.write('middle.vnt', '''
            import "base.vnt"

            func middle_value() -> i32:
                return base_value() + 1
        ''')
        self.write('main.vnt', '''
            import "middle.vnt"

            func main() -> void:
                print_i32(base_value())
                print_i32(middle_value())
        ''')
        self.check()

    def test_legacy_files_share_the_flat_namespace(self):
        self.write('a.vnt', '''
            func from_a() -> i32:
                return from_b()
        ''')
        self.write('b.vnt', '''
            func from_b() -> i32:
                return 7
        ''')
        self.write('main.vnt', '''
            import "a.vnt"
            import "b.vnt"

            func main() -> void:
                print_i32(from_a())
        ''')
        self.check()

    def test_declared_module_does_not_re_export_its_imports(self):
        self.write('b.vnt', '''
            module b

            pub func b_value() -> i32:
                return 2
        ''')
        self.write('a.vnt', '''
            module a

            import "b.vnt"

            pub func a_value() -> i32:
                return b_value()
        ''')
        self.write('main.vnt', '''
            import "a.vnt"

            func main() -> void:
                print_i32(a_value())
                print_i32(b_value())
        ''')
        with self.assertRaises(CheckError) as cm:
            self.check()
        self.assertIn("unknown callable 'b_value'", str(cm.exception))

    def test_qualified_const_in_elif_condition(self):
        self.write('flags.vnt', '''
            module flags

            pub const ENABLED: bool = true
        ''')
        self.write('main.vnt', '''
            import "flags.vnt" as flags

            func main() -> void:
                if false:
                    print_i32(1)
                elif flags.ENABLED:
                    print_i32(2)
                else:
                    print_i32(3)
        ''')
        self.check()

    def test_public_function_inferred_type_cannot_expose_private_type(self):
        self.write('secret.vnt', '''
            module secret

            struct Hidden:
                x: i32

            pub func make():
                return Hidden(x: 1)
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                let value = secret.make()
                print_i32(value.x)
        ''')
        with self.assertRaises(CheckError) as cm:
            self.check()
        self.assertIn("exposes private type 'Hidden'", str(cm.exception))
        self.assertIn("inferred type", str(cm.exception))

    def test_type_error_uses_source_name_not_internal_name(self):
        self.write('bad.vnt', '''
            module bad

            struct A:
                pub x: i32

            pub struct B:
                pub x: i32

            pub func broken(flag: bool):
                if flag:
                    return A(x: 1)
                else:
                    return B(x: 2)
        ''')
        self.write('main.vnt', '''
            import "bad.vnt" as bad

            func main() -> void:
                print_i32(bad.broken(true))
        ''')
        with self.assertRaises(CheckError) as cm:
            self.check()
        text = str(cm.exception)
        self.assertIn("function 'broken'", text)
        self.assertNotIn('vanta_m_bad__broken', text)

    # ---------- generic enums (v0.31.0) ----------

    def test_generic_enum_qualified_import(self):
        self.write('opt.vnt', '''
            module opt

            pub enum Option<T>:
                None
                Some(T)
        ''')
        self.write('main.vnt', '''
            import "opt.vnt" as opt

            func read(value: opt.Option<i32>) -> i32:
                match value:
                    opt.Option.None:
                        return 0
                    opt.Option.Some(v):
                        return v

            func main() -> void:
                let value: opt.Option<i32> = opt.Option.Some(4)
                print_i32(read(value))
        ''')
        _program, tc = self.check()
        family = 'vanta_m_opt__Option'
        self.assertIn(family, tc.generic_enums)
        self.assertTrue(any(et.family == family for et in tc.enums.values()))

    def test_stdlib_option_and_result_imports(self):
        self.write('main.vnt', '''
            import "std/option.vnt"
            import "std/result.vnt"

            func parse(n: i32) -> Result<i32, str>:
                if n < 0:
                    return Result.Err("negative")
                return Result.Ok(n)

            func main() -> void:
                let maybe: Option<i32> = Option.None
                match maybe:
                    Option.None:
                        print_i32(0)
                    Option.Some(v):
                        print_i32(v)
                match parse(7):
                    Result.Ok(v):
                        print_i32(v)
                    Result.Err(message):
                        print_str(message)
        ''')
        _program, tc = self.check()
        displays = {repr(et) for et in tc.enums.values()}
        self.assertIn('Option<i32>', displays)
        self.assertIn('Result<i32, str>', displays)

    def test_generic_type_argument_private_in_public_signature(self):
        self.write('secret.vnt', '''
            module secret

            enum Hidden:
                Value

            pub enum Option<T>:
                None
                Some(T)

            pub func leak(value: Option<Hidden>) -> void:
                return
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                print_i32(1)
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("exposes private type 'Hidden'", str(cm.exception))

    def test_inferred_generic_type_argument_private(self):
        self.write('secret.vnt', '''
            module secret

            enum Hidden:
                Value

            pub enum Option<T>:
                None
                Some(T)

            pub func leak():
                let value: Option<Hidden> = Option.None
                return value
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                print_i32(1)
        ''')
        with self.assertRaises(CheckError) as cm:
            self.check()
        text = str(cm.exception)
        self.assertIn("exposes private type 'Hidden'", text)
        self.assertIn('inferred type', text)

    def test_private_generic_family_in_public_signature(self):
        self.write('secret.vnt', '''
            module secret

            enum Option<T>:
                None
                Some(T)

            pub func leak() -> Option<i32>:
                return Option.None
        ''')
        self.write('main.vnt', '''
            import "secret.vnt" as secret

            func main() -> void:
                print_i32(1)
        ''')
        with self.assertRaises(LoadError) as cm:
            self.check()
        self.assertIn("exposes private type 'Option'", str(cm.exception))

    def test_same_generic_name_in_two_modules(self):
        self.write('alpha.vnt', '''
            module alpha

            pub enum Option<T>:
                None
                Some(T)
        ''')
        self.write('beta.vnt', '''
            module beta

            pub enum Option<T>:
                None
                Some(T)
        ''')
        self.write('main.vnt', '''
            import "alpha.vnt" as a
            import "beta.vnt" as b

            func main() -> void:
                let x: a.Option<i32> = a.Option.None
                let y: b.Option<str> = b.Option.Some("x")
                print_i32(1)
        ''')
        _program, tc = self.check()
        families = {et.family for et in tc.enums.values()}
        self.assertIn('vanta_m_alpha__Option', families)
        self.assertIn('vanta_m_beta__Option', families)


if __name__ == '__main__':
    unittest.main()
