import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.type_checker import TypeChecker, CheckError


def run(src):
    toks = Lexer(src).tokenize()
    prog = Parser(toks).parse_program()
    tc = TypeChecker(prog)
    tc.register()
    tc.check()
    return prog, tc


class TypeCheckerTests(unittest.TestCase):
    def test_inference(self):
        run("func f() -> void:\n    let x = 100\n    let y = 3.5\n")

    def test_type_mismatch(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let x: i32 = 3.5\n")

    def test_unknown_name(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    y = 1\n")

    def test_bad_call(self):
        with self.assertRaises(CheckError):
            run("func g(a: i32) -> void:\n    return\n"
                "func f() -> void:\n    g(1, 2)\n")

    def test_immutable_assignment(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let x = 1\n    x = 2\n")

    def test_bad_return(self):
        with self.assertRaises(CheckError):
            run("func f() -> i32:\n    return\n")

    def test_arena_copy_rejected(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let a = Arena(64)\n    let b = a\n")

    def test_ok_arena(self):
        run("func f() -> void:\n    let a = Arena(64)\n    let p = a.alloc::<i32>(4)\n    p[0] = 7\n")

    def test_nested_index_write_through_ptr(self):
        run("func f() -> void:\n"
            "    let arena = Arena(1024)\n"
            "    let rows = arena.alloc::<[i32, 4]>(2)\n"
            "    rows[0][1] = 5\n")

    def test_nested_index_write_through_mut_struct(self):
        run("struct B:\n    cells: [[i32, 2], 2]\n"
            "func f() -> void:\n"
            "    mut b = B(cells: [[1, 2], [3, 4]])\n"
            "    b.cells[1][0] = 5\n")

    def test_nested_index_write_rejected_on_let_array(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let xs = [[1, 2], [3, 4]]\n"
                "    xs[0][1] = 5\n")

    def test_field_array_write_rejected_on_param(self):
        with self.assertRaises(CheckError):
            run("struct B:\n    cells: [[i32, 2], 2]\n"
                "func f(b: B) -> void:\n"
                "    b.cells[0][0] = 1\n")

    def test_deep_field_write_through_mut(self):
        run("struct In:\n    x: i32\n"
            "struct Out:\n    inner: In\n"
            "func f() -> void:\n"
            "    mut o = Out(inner: In(x: 1))\n"
            "    o.inner.x = 2\n")

    def test_void_func_no_value_return(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    return 3\n")

    def test_break_outside_loop(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    break\n")

    def test_continue_outside_loop(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    continue\n")

    def test_break_in_loop_ok(self):
        run("func f() -> void:\n    for i in range(0, 10):\n        break\n")

    def test_continue_in_while_ok(self):
        run("func f() -> void:\n    mut c = true\n    while c:\n        continue\n")

    def test_compound_assign_mutable(self):
        run("func f() -> void:\n    mut x = 1\n    x += 2\n    x -= 1\n    x *= 3\n")

    def test_compound_assign_immutable(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let x = 1\n    x += 2\n")

    def test_compound_assign_type_mismatch(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    mut x: i32 = 1\n    x += 1.5\n")

    def test_const_inference(self):
        prog, tc = run("const X = 5\n")
        self.assertEqual(tc.constants['X'], __import__('compiler.typesys', fromlist=['I32']).I32)

    def test_const_typed(self):
        from compiler.typesys import F32
        prog, tc = run("const G: f32 = 9.8\n")
        self.assertEqual(tc.constants['G'], F32)

    def test_const_not_assignable(self):
        with self.assertRaises(CheckError):
            run("const X = 5\nfunc f() -> void:\n    X = 10\n")

    def test_const_duplicate(self):
        with self.assertRaises(CheckError):
            run("const X = 1\nconst X = 2\n")

    def test_const_non_constexpr(self):
        with self.assertRaises(CheckError):
            run("func g() -> i32:\n    return 1\nconst X = g()\n")

    def test_return_inference_i32(self):
        from compiler.typesys import I32
        prog, tc = run("func add(a: i32, b: i32):\n    return a + b\n")
        self.assertEqual(tc.functions['add'].ret, I32)

    def test_return_inference_void(self):
        from compiler.typesys import VOID
        prog, tc = run("func f():\n    print_i32(1)\n")
        self.assertEqual(tc.functions['f'].ret, VOID)

    def test_return_inference_mixed_error(self):
        # Mixed LITERAL returns are allowed (1 coerces to F32 because 1.5 is
        # FLOAT_LIT, and float wins). This test exercises the case where both
        # returns are already CONCRETE and disagree.
        with self.assertRaises(CheckError):
            run("func f(x: bool, a: i32, b: f32):\n    if x:\n        return a\n    return b\n")

    def test_range_step_zero(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    for i in range(0, 10, 0):\n        print_i32(i)\n")

    def test_assert_bool_ok(self):
        run("func f() -> void:\n    assert(1 == 1)\n")

    def test_assert_nonbool(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    assert(1)\n")

    def test_vec3_eq(self):
        from compiler.typesys import BOOL
        prog, tc = run("func f() -> void:\n    let a = Vec3(1.0, 2.0, 3.0)\n    let b = Vec3(1.0, 2.0, 3.0)\n    let c = a == b\n")
        # Just check it type-checks (BOOL is the type of c)

    def test_matrix4_vec3(self):
        run("func f() -> void:\n    let m = Matrix4()\n    let v = Vec3(1.0, 2.0, 3.0)\n    let r = m * v\n")

    def test_array_inference(self):
        from compiler.typesys import I32, ArrayType
        prog, tc = run("func f() -> void:\n    let xs = [1, 2, 3, 4]\n")
        v = prog.decls[0].body[0]
        self.assertEqual(v.var_type, ArrayType(I32, 4))

    def test_array_f32_coercion(self):
        from compiler.typesys import F32, ArrayType
        prog, tc = run("func f() -> void:\n    let xs: [f32, 3] = [1, 2, 3]\n")
        v = prog.decls[0].body[0]
        self.assertEqual(v.var_type, ArrayType(F32, 3))

    def test_array_size_mismatch(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let xs: [i32, 3] = [1, 2, 3, 4]\n")

    def test_array_index_assign_mutable(self):
        run("func f() -> void:\n    mut xs = [1, 2, 3]\n    xs[0] = 5\n")

    def test_array_index_assign_immutable(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let xs = [1, 2, 3]\n    xs[0] = 5\n")

    def test_array_compound_assign_element(self):
        run("func f() -> void:\n    mut xs = [1, 2, 3]\n    xs[0] += 10\n")

    def test_len_array(self):
        from compiler.typesys import I32
        prog, tc = run("func f() -> void:\n    let xs = [1, 2, 3]\n    let n = len(xs)\n")
        n_decl = prog.decls[0].body[1]
        self.assertEqual(n_decl.var_type, I32)

    def test_len_non_array(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let n = len(5)\n")

    def test_empty_array_rejected(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let xs = []\n")

    def test_quat_vec3_mul(self):
        from compiler.typesys import F32
        prog, tc = run("func f() -> void:\n    let q = Quat(0.0, 0.0, 0.0, 1.0)\n    let v = Vec3(1.0, 0.0, 0.0)\n    let r = q * v\n")
        r_decl = prog.decls[0].body[2]
        self.assertEqual(r_decl.var_type.name, 'Vec3')

    def test_quat_quat_mul(self):
        prog, tc = run("func f() -> void:\n    let a = Quat(0.0, 0.0, 0.0, 1.0)\n    let b = Quat(0.0, 0.0, 0.0, 1.0)\n    let c = a * b\n")
        c_decl = prog.decls[0].body[2]
        self.assertEqual(c_decl.var_type.name, 'Quat')

    def test_matrix4_matrix4_mul(self):
        prog, tc = run("func f() -> void:\n    let a = Matrix4()\n    let b = Matrix4()\n    let c = a * b\n")
        c_decl = prog.decls[0].body[2]
        self.assertEqual(c_decl.var_type.name, 'Matrix4')

    def test_str_inference(self):
        from compiler.typesys import STR
        prog, tc = run('func f() -> void:\n    let s = "hi"\n')
        v = prog.decls[0].body[0]
        self.assertEqual(v.var_type, STR)

    def test_print_str_ok(self):
        run('func f() -> void:\n    print_str("hi")\n')

    def test_str_eq(self):
        from compiler.typesys import BOOL
        prog, tc = run('func f() -> void:\n    let b = "a" == "b"\n')
        b_decl = prog.decls[0].body[0]
        self.assertEqual(b_decl.var_type, BOOL)

    def test_str_ordering_rejected(self):
        with self.assertRaises(CheckError):
            run('func f() -> void:\n    let b = "a" < "b"\n')

    def test_str_const(self):
        from compiler.typesys import STR
        prog, tc = run('const GREETING = "hello"\n')
        self.assertEqual(tc.constants['GREETING'], STR)

    def test_vec2_normalized(self):
        prog, tc = run("func f() -> void:\n    let v = Vec2(3.0, 4.0)\n    let n = v.normalized()\n")
        n_decl = prog.decls[0].body[1]
        self.assertEqual(n_decl.var_type.name, 'Vec2')

    def test_quat_dot(self):
        from compiler.typesys import F32
        prog, tc = run("func f() -> void:\n    let a = Quat(0.0, 0.0, 0.0, 1.0)\n    let b = Quat(0.0, 0.0, 0.0, 1.0)\n    let d = a.dot(b)\n")
        d_decl = prog.decls[0].body[2]
        self.assertEqual(d_decl.var_type, F32)

    def test_translation_builtin(self):
        prog, tc = run("func f() -> void:\n    let m = translation(1.0, 2.0, 3.0)\n")
        m_decl = prog.decls[0].body[0]
        self.assertEqual(m_decl.var_type.name, 'Matrix4')

    def test_scale_builtin(self):
        prog, tc = run("func f() -> void:\n    let m = scale(2.0)\n")
        m_decl = prog.decls[0].body[0]
        self.assertEqual(m_decl.var_type.name, 'Matrix4')

    def test_from_quat_builtin(self):
        prog, tc = run("func f() -> void:\n    let q = Quat(0.0, 0.0, 0.0, 1.0)\n    let m = from_quat(q)\n")
        m_decl = prog.decls[0].body[1]
        self.assertEqual(m_decl.var_type.name, 'Matrix4')


    def test_rand_f32_builtin(self):
        from compiler.typesys import F32
        prog, tc = run("func f() -> void:\n    let r = rand_f32()\n")
        r_decl = prog.decls[0].body[0]
        self.assertEqual(r_decl.var_type, F32)

    def test_rand_seed_builtin(self):
        run("func f() -> void:\n    rand_seed(1234)\n")

    def test_rand_seed_i32_variable(self):
        from compiler.typesys import I32
        prog, tc = run("func f() -> void:\n    mut s: i32 = 7\n    rand_seed(s)\n")
        s_decl = prog.decls[0].body[0]
        self.assertEqual(s_decl.var_type, I32)

    def test_rand_seed_bad_arg(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    rand_seed(1.5)\n")

    def test_rand_f32_arity(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let r = rand_f32(1)\n")


    def test_write_and_newline_builtins(self):
        run("func f() -> void:\n    write_str(\"x\")\n    print_newline()\n")

    def test_write_i32_rejects_float(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    write_i32(1.5)\n")

    def test_abs_i32_type(self):
        from compiler.typesys import I32
        prog, tc = run("func f() -> void:\n    let a = abs_i32(-3)\n")
        self.assertEqual(prog.decls[0].body[0].var_type, I32)

    def test_min_f32_arity(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let m = min_f32(1.0)\n")

    def test_floor_f32_type(self):
        from compiler.typesys import F32
        prog, tc = run("func f() -> void:\n    let f = floor_f32(1.7)\n")
        self.assertEqual(prog.decls[0].body[0].var_type, F32)


    def test_arg_builtins(self):
        from compiler.typesys import I32, STR
        prog, tc = run("func f() -> void:\n    let n = arg_count()\n    let a = arg_str(0)\n")
        self.assertEqual(prog.decls[0].body[0].var_type, I32)
        self.assertEqual(prog.decls[0].body[1].var_type, STR)

    def test_arg_str_rejects_float(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    arg_str(1.5)\n")


    def test_print_fmt_ok(self):
        run("func f() -> void:\n    print_fmt(\"n={} f={}\", 1, 2.0)\n")

    def test_print_fmt_placeholder_count(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    print_fmt(\"{} {}\", 1)\n")
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    print_fmt(\"{}\", 1, 2)\n")

    def test_print_fmt_requires_literal(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let s = \"x{}\"\n    print_fmt(s, 1)\n")

    def test_print_fmt_rejects_unformattable(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    let v = Vec2(1.0, 2.0)\n    print_fmt(\"{}\", v)\n")

    def test_fmt_unmatched_brace(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    print_fmt(\"oops {\", 1)\n")

    def test_str_concat_and_len_types(self):
        from compiler.typesys import STR, I32
        prog, tc = run("func f() -> void:\n"
                       "    let s = str_concat(\"a\", \"b\")\n"
                       "    let n = str_len(s)\n")
        self.assertEqual(prog.decls[0].body[0].var_type, STR)
        self.assertEqual(prog.decls[0].body[1].var_type, I32)

    def test_to_str_types(self):
        from compiler.typesys import STR
        prog, tc = run("func f() -> void:\n"
                       "    let a = to_str_i32(1)\n"
                       "    let b = to_str_f32(1.0)\n"
                       "    let c = to_str_bool(true)\n")
        for decl in prog.decls[0].body:
            self.assertEqual(decl.var_type, STR)


    def test_str_to_number_types(self):
        from compiler.typesys import I32, F32
        prog, tc = run("func f() -> void:\n"
                       "    let a = str_to_i32(\"12\")\n"
                       "    let b = str_to_f32(\"1.5\")\n")
        self.assertEqual(prog.decls[0].body[0].var_type, I32)
        self.assertEqual(prog.decls[0].body[1].var_type, F32)

    def test_file_io_builtins_types(self):
        from compiler.typesys import BOOL, I32, STR
        prog, tc = run("func f() -> void:\n"
                       "    let e = file_exists(\"a\")\n"
                       "    let w = file_write(\"a\", \"b\")\n"
                       "    let r = file_read(\"a\")\n")
        self.assertEqual(prog.decls[0].body[0].var_type, BOOL)
        self.assertEqual(prog.decls[0].body[1].var_type, I32)
        self.assertEqual(prog.decls[0].body[2].var_type, STR)

    def test_file_read_rejects_non_str(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    file_read(1)\n")

    def test_file_write_rejects_non_str_data(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    file_write(\"a\", 2)\n")

    def test_extern_registered(self):
        from compiler.typesys import VOID, I32
        prog, tc = run('extern "c" {\n'
                       '    func add(a: i32, b: i32) -> i32\n'
                       '    func log()\n'
                       '}\n')
        add = tc.functions['add']
        self.assertTrue(add.is_extern)
        self.assertEqual(add.ret, I32)
        log = tc.functions['log']
        self.assertTrue(log.is_extern)
        self.assertEqual(log.ret, VOID)

    def test_extern_call_ok(self):
        run('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
            'func f() -> i32:\n    return add(1, 2)\n')

    def test_extern_call_arity_error(self):
        with self.assertRaises(CheckError):
            run('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
                'func f() -> i32:\n    return add(1)\n')

    def test_extern_call_type_error(self):
        with self.assertRaises(CheckError):
            run('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
                'func f() -> i32:\n    return add(1, 2.5)\n')

    def test_extern_duplicate_name(self):
        with self.assertRaises(CheckError):
            run('extern "a" {\n    func f()\n}\n'
                'extern "b" {\n    func f()\n}\n')

    def test_extern_collides_with_vanta_func(self):
        with self.assertRaises(CheckError):
            run('func g() -> void:\n    return\n'
                'extern "c" {\n    func g()\n}\n')

    def test_extern_collides_with_struct(self):
        with self.assertRaises(CheckError):
            run('struct P:\n    x: i32\n'
                'extern "c" {\n    func P()\n}\n')

    def test_extern_collides_with_builtin(self):
        with self.assertRaises(CheckError):
            run('extern "c" {\n    func print_i32(v: i32)\n}\n')

    def test_function_value_annotated(self):
        from compiler.typesys import FuncType, I32
        prog, tc = run("func sq(x: i32) -> i32:\n    return x\n"
                       "func f() -> void:\n"
                       "    let g: func(i32) -> i32 = sq\n")
        v = prog.decls[1].body[0]
        self.assertEqual(v.var_type, FuncType((I32,), I32))
        self.assertTrue(getattr(v.value, 'is_func_ref', False))

    def test_function_value_inferred(self):
        from compiler.typesys import FuncType, I32
        prog, tc = run("func sq(x: i32) -> i32:\n    return x\n"
                       "func f() -> void:\n    let g = sq\n")
        self.assertEqual(prog.decls[1].body[0].var_type, FuncType((I32,), I32))

    def test_function_value_from_builtin(self):
        from compiler.typesys import FuncType, F32
        prog, tc = run("func f() -> void:\n"
                       "    let sq: func(f32) -> f32 = sqrt_f32\n"
                       "    print_f32(sq(4.0))\n")
        self.assertEqual(prog.decls[0].body[0].var_type, FuncType((F32,), F32))

    def test_function_value_from_extern(self):
        run('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
            'func f() -> void:\n'
            '    let op: func(i32, i32) -> i32 = add\n'
            '    print_i32(op(1, 2))\n')

    def test_function_value_void_shorthand(self):
        run("func f() -> void:\n"
            "    let logger: func(str) = print_str\n"
            "    logger(\"hi\")\n")

    def test_indirect_call_return_type(self):
        from compiler.typesys import I32
        prog, tc = run("func sq(x: i32) -> i32:\n    return x\n"
                       "func f() -> i32:\n"
                       "    let g: func(i32) -> i32 = sq\n"
                       "    return g(3)\n")
        self.assertEqual(prog.decls[1].body[1].value.type, I32)

    def test_indirect_call_arity_error(self):
        with self.assertRaises(CheckError):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let g: func(i32) -> i32 = sq\n"
                "    g(1, 2)\n")

    def test_indirect_call_type_error(self):
        with self.assertRaises(CheckError):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let g: func(i32) -> i32 = sq\n"
                "    g(true)\n")

    def test_indirect_call_named_args_rejected(self):
        with self.assertRaises(CheckError):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let g: func(i32) -> i32 = sq\n"
                "    g(x: 1)\n")

    def test_indirect_call_type_args_rejected(self):
        with self.assertRaises(CheckError):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let g: func(i32) -> i32 = sq\n"
                "    g::<i32>(1)\n")

    def test_len_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'len' as a value"):
            run("func f() -> void:\n    let g = len\n")

    def test_format_builtins_as_values_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'print_fmt' as a value"):
            run("func f() -> void:\n    let g = print_fmt\n")
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'write_fmt' as a value"):
            run("func f() -> void:\n    let g = write_fmt\n")

    def test_assert_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'assert' as a value"):
            run("func f() -> void:\n    let g = assert\n")

    def test_type_name_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use type 'Vec3' as a value"):
            run("func f() -> void:\n    let g = Vec3\n")

    def test_function_equality(self):
        run("func sq(x: i32) -> i32:\n    return x\n"
            "func f() -> void:\n"
            "    let a = sq\n"
            "    let b = sq\n"
            "    let same: bool = a == b\n"
            "    print_bool(a != b)\n")

    def test_function_equality_different_types_rejected(self):
        with self.assertRaisesRegex(
                CheckError,
                r"cannot compare func\(i32\) -> i32 and func\(i32\) -> bool with '=='"):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func pos(x: i32) -> bool:\n    return x > 0\n"
                "func f() -> void:\n"
                "    let a = sq\n"
                "    let b = pos\n"
                "    print_bool(a == b)\n")

    def test_function_ordering_rejected(self):
        with self.assertRaisesRegex(
                CheckError,
                "ordering comparisons are not supported on function values"):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let a = sq\n"
                "    print_bool(a < a)\n")

    def test_function_equality_with_null(self):
        run("func sq(x: i32) -> i32:\n    return x\n"
            "func f() -> void:\n"
            "    let a = sq\n"
            "    let n: func(i32) -> i32 = ptr_null::<func(i32) -> i32>()\n"
            "    print_bool(a != n)\n"
            "    print_bool(ptr_is_null(n))\n"
            "    print_bool(ptr_is_null(a))\n")

    def test_const_function_rejected(self):
        with self.assertRaisesRegex(CheckError, "constant cannot hold a function value"):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "const G = sq\n"
                "func f() -> void:\n    print_i32(G(1))\n")

    def test_extern_callback_params_ok(self):
        run('extern "c" {\n'
            '    func on_event(cb: func(i32) -> bool) -> void\n'
            '    func run_all(cb: func()) -> void\n'
            '    func is_big_ext(x: i32) -> bool\n'
            '    func forward(cb: func(i32) -> bool) -> void\n'
            '}\n'
            'func is_big(x: i32) -> bool:\n'
            '    return x > 10\n'
            'func tick():\n'
            '    return\n'
            'func f() -> void:\n'
            '    on_event(is_big)\n'
            '    run_all(tick)\n'
            '    forward(is_big_ext)\n')

    def test_extern_callback_wrong_signature(self):
        with self.assertRaisesRegex(
                CheckError,
                r"argument: cannot assign func\(i32\) -> bool to func\(i32\) -> i32"):
            run('extern "c" {\n    func on(cb: func(i32) -> i32) -> void\n}\n'
                'func bad(x: i32) -> bool:\n    return x > 0\n'
                'func f() -> void:\n    on(bad)\n')

    def test_extern_callback_needs_function(self):
        with self.assertRaisesRegex(
                CheckError, r"argument: cannot assign i32 to func\(i32\) -> i32"):
            run('extern "c" {\n    func on(cb: func(i32) -> i32) -> void\n}\n'
                'func f() -> void:\n    let n: i32 = 3\n    on(n)\n')

    def test_extern_func_return_ok(self):
        run('extern "c" {\n'
            '    func get() -> func(i32) -> i32\n'
            '    func get_ptr() -> ptr<func()>\n'
            '    func get_nested() -> func() -> func() -> i32\n'
            '}\n'
            'func f() -> void:\n'
            '    let g = get()\n'
            '    print_i32(g(1))\n'
            '    let p = get_ptr()\n'
            '    print_bool(ptr_is_null(p))\n'
            '    let h = get_nested()\n'
            '    let h2 = h()\n'
            '    print_i32(h2())\n')

    def test_extern_func_return_array_rejected(self):
        with self.assertRaisesRegex(
                CheckError,
                "can return a function type or a pointer to one"):
            run('extern "c" {\n    func get() -> [func(), 2]\n}\n'
                'func f() -> void:\n    return\n')

    def test_reserved_fnptr_struct_name_rejected(self):
        with self.assertRaisesRegex(CheckError,
                                    "reserved for generated function-pointer aliases"):
            run("struct FnPtr0:\n    x: i32\n"
                "func f() -> void:\n    return\n")

    def test_call_non_function_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot call a value of type i32"):
            run("func f() -> void:\n    let x = 3\n    x()\n")

    def test_function_value_argument_mismatch_rejected(self):
        with self.assertRaises(CheckError):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func takes(x: i32) -> void:\n    return\n"
                "func f() -> void:\n    takes(sq)\n")

    def test_function_as_param_and_return(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func apply(f: func(i32) -> i32, x: i32) -> i32:\n    return f(x)\n"
            "func pick() -> func(i32) -> i32:\n    return inc\n"
            "func f() -> i32:\n"
            "    let h = pick()\n"
            "    return apply(h, 1)\n")

    def test_struct_field_function_value(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "struct H:\n    cb: func(i32) -> i32\n"
            "func f() -> i32:\n"
            "    let h = H(cb: inc)\n"
            "    return h.cb(2)\n")

    def test_struct_non_function_field_call_rejected(self):
        with self.assertRaisesRegex(CheckError, "field 'x' is not callable"):
            run("struct P:\n    x: i32\n"
                "func f() -> void:\n    let p = P(x: 1)\n    p.x()\n")

    def test_array_of_functions_index_call(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func dec(x: i32) -> i32:\n    return x - 1\n"
            "func f() -> i32:\n"
            "    let fs: [func(i32) -> i32, 2] = [inc, dec]\n"
            "    return fs[0](10) + fs[1](10)\n")

    def test_mutable_function_variable_reassign(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func dec(x: i32) -> i32:\n    return x - 1\n"
            "func f() -> i32:\n"
            "    mut g: func(i32) -> i32 = inc\n"
            "    g = dec\n"
            "    return g(5)\n")

    def test_immutable_function_variable_assignment_rejected(self):
        with self.assertRaises(CheckError):
            run("func inc(x: i32) -> i32:\n    return x + 1\n"
                "func dec(x: i32) -> i32:\n    return x - 1\n"
                "func f() -> void:\n"
                "    let g: func(i32) -> i32 = inc\n"
                "    g = dec\n")

    def test_function_value_before_inference_rejected(self):
        with self.assertRaisesRegex(CheckError, "before its return type is inferred"):
            run("func f() -> void:\n"
                "    let g = helper\n"
                "func helper(x: i32):\n    return x\n")

    def test_function_value_condition_rejected(self):
        with self.assertRaises(CheckError):
            run("func inc(x: i32) -> i32:\n    return x + 1\n"
                "func f() -> void:\n"
                "    let g = inc\n"
                "    if g:\n        print_i32(1)\n")

    def test_alloc_of_function_type(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func f() -> i32:\n"
            "    let a = Arena(256)\n"
            "    let slots = a.alloc::<func(i32) -> i32>(2)\n"
            "    slots[0] = inc\n"
            "    return slots[0](3)\n")

    def test_nested_function_type(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func twice(f: func(i32) -> i32, x: i32) -> i32:\n    return f(f(x))\n"
            "func f() -> i32:\n"
            "    let t: func(func(i32) -> i32, i32) -> i32 = twice\n"
            "    return t(inc, 1)\n")

    def test_func_types_registered_for_codegen(self):
        prog, tc = run("func inc(x: i32) -> i32:\n    return x + 1\n"
                       "func f() -> void:\n    let g = inc\n")
        self.assertEqual(list(tc.func_types.values()), ['FnPtr0'])

    def test_at_read_returns_element_type(self):
        from compiler.typesys import I32
        prog, tc = run("func f() -> i32:\n"
                       "    let xs: [i32, 3] = [1, 2, 3]\n"
                       "    return xs.at(1)\n")
        self.assertEqual(prog.decls[0].body[1].value.type, I32)

    def test_at_marks_checked_call(self):
        prog, tc = run("func f() -> i32:\n"
                       "    let xs: [i32, 3] = [1, 2, 3]\n"
                       "    return xs.at(1)\n")
        self.assertTrue(getattr(prog.decls[0].body[1].value, 'is_checked_at', False))

    def test_at_nested_array_read(self):
        run("func f() -> i32:\n"
            "    let g: [[i32, 2], 2] = [[1, 2], [3, 4]]\n"
            "    return g.at(1).at(0)\n")

    def test_at_read_on_field_and_row(self):
        run("struct S:\n    arr: [i32, 2]\n"
            "func f() -> i32:\n"
            "    let s = S(arr: [1, 2])\n"
            "    return s.arr.at(1)\n"
            "func g() -> i32:\n"
            "    let a = Arena(256)\n"
            "    let rows = a.alloc::<[i32, 2]>(2)\n"
            "    return rows[1].at(0)\n")

    def test_at_write_mut_array(self):
        run("func f() -> void:\n"
            "    mut xs: [i32, 3] = [1, 2, 3]\n"
            "    xs.at(0) = 9\n")

    def test_at_compound_write(self):
        run("func f() -> void:\n"
            "    mut xs: [i32, 3] = [1, 2, 3]\n"
            "    xs.at(0) += 2\n")

    def test_at_write_rejected_on_let(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    xs.at(0) = 9\n")

    def test_at_write_rejected_on_param(self):
        with self.assertRaises(CheckError):
            run("func f(xs: [i32, 3]) -> void:\n"
                "    xs.at(0) = 9\n"
                "func main() -> void:\n    return\n")

    def test_at_write_rejected_on_temp(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    [1, 2].at(0) = 9\n")

    def test_at_write_through_mut_struct_field(self):
        run("struct S:\n    arr: [i32, 2]\n"
            "func f() -> void:\n"
            "    mut s = S(arr: [1, 2])\n"
            "    s.arr.at(0) = 9\n")

    def test_at_write_through_pointer_row(self):
        run("func f() -> void:\n"
            "    let a = Arena(256)\n"
            "    let rows = a.alloc::<[i32, 2]>(2)\n"
            "    rows[0].at(1) = 7\n")

    def test_at_write_nested_arrays(self):
        run("func f() -> void:\n"
            "    mut g: [[i32, 2], 2] = [[1, 2], [3, 4]]\n"
            "    g.at(0).at(1) = 7\n")

    def test_at_on_pointer_requires_size(self):
        with self.assertRaisesRegex(CheckError, "p.at\\(i, size\\)"):
            run("func f() -> void:\n"
                "    let a = Arena(64)\n"
                "    let p = a.alloc::<i32>(4)\n"
                "    print_i32(p.at(0))\n")

    def test_at_write_through_let_pointer(self):
        # Pointer memory is writable through a plain `let`, checked or not.
        run("func f() -> void:\n"
            "    let a = Arena(64)\n"
            "    let p = a.alloc::<i32>(4)\n"
            "    p.at(0, 4) = 7\n"
            "    p.at(0, 4) += 1\n")

    def test_at_rejected_on_void_pointer(self):
        with self.assertRaisesRegex(CheckError, "ptr<void>"):
            run("func f(p: ptr<void>) -> void:\n"
                "    print_i32(p.at(0, 4))\n")

    def test_at_pointer_size_type(self):
        with self.assertRaisesRegex(CheckError, "size: cannot assign f32 to i32"):
            run("func f() -> void:\n"
                "    let a = Arena(64)\n"
                "    let p = a.alloc::<i32>(4)\n"
                "    let n: f32 = 4.0\n"
                "    print_i32(p.at(0, n))\n")

    def test_at_rejected_on_non_array(self):
        with self.assertRaisesRegex(CheckError, "'at' requires an array, a List, or a pointer"):
            run("func f() -> void:\n"
                "    let x = 1\n"
                "    print_i32(x.at(0))\n")

    def test_at_arity_error(self):
        with self.assertRaisesRegex(CheckError, "'at' expects one index"):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    print_i32(xs.at(0, 1))\n")

    def test_at_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'at' does not accept named arguments"):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    print_i32(xs.at(i: 0))\n")

    def test_at_type_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'at' does not accept type arguments"):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    print_i32(xs.at::<i32>(0))\n")

    def test_at_index_must_be_i32(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    print_i32(xs.at(1.5))\n")

    def test_at_value_use_rejected(self):
        with self.assertRaisesRegex(CheckError, "'at' must be called with an index"):
            run("func f() -> void:\n"
                "    let xs: [i32, 3] = [1, 2, 3]\n"
                "    let f = xs.at\n")

    def test_at_field_name_still_wins_on_struct(self):
        run("struct Op:\n    at: func(i32) -> i32\n"
            "func inc(x: i32) -> i32:\n    return x + 1\n"
            "func f() -> i32:\n"
            "    let o = Op(at: inc)\n"
            "    return o.at(41)\n")

    def test_at_field_call_result_not_assignable(self):
        with self.assertRaisesRegex(CheckError, "invalid assignment target"):
            run("struct Op:\n    at: func(i32) -> i32\n"
                "func inc(x: i32) -> i32:\n    return x + 1\n"
                "func f() -> void:\n"
                "    let o = Op(at: inc)\n"
                "    o.at(1) = 2\n")

    def test_trig_builtins(self):
        run("func f() -> void:\n"
            "    print_f32(sin_f32(0.0))\n"
            "    print_f32(cos_f32(0.0))\n"
            "    print_f32(tan_f32(0.0))\n"
            "    print_f32(atan2_f32(1.0, 1.0))\n"
            "    print_f64(sin_f64(0.0))\n"
            "    print_f64(cos_f64(0.0))\n"
            "    print_f64(tan_f64(0.0))\n"
            "    print_f64(atan2_f64(1.0, 1.0))\n")

    def test_trig_builtin_bad_type(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    print_f32(sin_f32(true))\n")

    def test_trig_builtin_arity_error(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n    print_f32(sin_f32())\n")

    def test_trig_builtin_as_value(self):
        run("func f() -> void:\n"
            "    let g: func(f32) -> f32 = sin_f32\n"
            "    print_f32(g(1.5707964))\n")

    def test_list_create_and_type(self):
        run("func f() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let xs: List<i32> = a.list::<i32>()\n"
            "    print_i32(len(xs))\n")

    def test_list_requires_type_argument(self):
        with self.assertRaisesRegex(CheckError, "list requires a type argument"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let xs = a.list()\n")

    def test_list_takes_no_arguments(self):
        with self.assertRaisesRegex(CheckError, "takes no arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let xs = a.list::<i32>(8)\n")

    def test_list_type_requires_brackets(self):
        with self.assertRaisesRegex(CheckError, "List requires an element type"):
            run("func f() -> void:\n"
                "    let x: List = 1\n")

    def test_list_cannot_hold_void_or_arena(self):
        with self.assertRaisesRegex(CheckError, "cannot hold void"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let xs = a.list::<void>()\n")
        with self.assertRaisesRegex(CheckError, "cannot hold Arena"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let xs = a.list::<Arena>()\n")

    def test_list_reserved_struct_name(self):
        with self.assertRaisesRegex(CheckError, "reserved built-in type name"):
            run("struct List:\n    x: i32\n")

    def test_list_ctor_hint(self):
        with self.assertRaisesRegex(CheckError, "a List is created from an Arena"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let xs = List(a)\n")

    def test_list_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use type 'List' as a value"):
            run("func f() -> void:\n"
                "    let x = List\n")

    def test_list_push_len_at(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(1)\n"
            "    xs.push(2)\n"
            "    print_i32(len(xs))\n"
            "    print_i32(xs.at(1))\n"
            "    print_i32(xs[0])\n")

    def test_list_write_through_let(self):
        # A List is an indirection: writes need no `mut`.
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    xs.push(1)\n"
            "    xs[0] = 5\n"
            "    xs.at(0) += 1\n"
            "    xs.push(2)\n"
            "    print_i32(xs.pop())\n")

    def test_list_pop_is_element_typed(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<f32>()\n"
            "    xs.push(1.5)\n"
            "    print_f32(xs.pop())\n")

    def test_list_rebind_requires_mut(self):
        with self.assertRaisesRegex(CheckError, "invalid assignment target"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs = a.list::<i32>()\n")

    def test_list_rebind_with_mut_ok(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    mut xs = a.list::<i32>()\n"
            "    xs.push(1)\n"
            "    xs = a.list::<i32>()\n"
            "    print_i32(len(xs))\n")

    def test_list_element_type_mismatch(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.push(1.5)\n")

    def test_list_push_arity(self):
        with self.assertRaisesRegex(CheckError, "'push' expects one value"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.push(1, 2)\n")

    def test_list_push_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'push' does not accept named arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.push(v: 1)\n")

    def test_list_pop_takes_no_args(self):
        with self.assertRaisesRegex(CheckError, "'pop' takes no arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    print_i32(xs.pop(1))\n")

    def test_list_len_method_hint(self):
        with self.assertRaisesRegex(CheckError, "write len\\(xs\\)"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    print_i32(xs.len())\n")

    def test_list_insert_remove_sort(self):
        run("struct Item:\n"
            "    key: i32\n"
            "\n"
            "func by_key(a: Item, b: Item) -> i32:\n"
            "    return a.key - b.key\n"
            "\n"
            "func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<Item>()\n"
            "    xs.insert(0, Item(key: 1))\n"
            "    let it = xs.remove(0)\n"
            "    xs.push(it)\n"
            "    xs.sort(by_key)\n")

    def test_list_insert_arity(self):
        with self.assertRaisesRegex(CheckError, "'insert' expects an index and a value"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.insert(0)\n")

    def test_list_insert_index_type(self):
        with self.assertRaisesRegex(CheckError, "index: cannot assign f32 to i32"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    let k: f32 = 0.0\n"
                "    xs.insert(k, 1)\n")

    def test_list_insert_element_type(self):
        with self.assertRaisesRegex(CheckError, "list element: cannot assign f32 to i32"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    let v: f32 = 1.5\n"
                "    xs.insert(0, v)\n")

    def test_list_insert_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'insert' does not accept named arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.insert(i: 0, v: 1)\n")

    def test_list_remove_arity(self):
        with self.assertRaisesRegex(CheckError, "'remove' expects one index"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.remove(0, 1)\n")

    def test_list_remove_is_element_typed(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<f32>()\n"
            "    xs.push(1.5)\n"
            "    print_f32(xs.remove(0))\n")

    def test_list_sort_arity(self):
        with self.assertRaisesRegex(CheckError, "'sort' expects one comparator"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.sort(1, 2)\n")

    def test_list_sort_needs_comparator(self):
        with self.assertRaisesRegex(
                CheckError,
                r"'sort' expects a comparator func\(i32, i32\) -> i32, got i32"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.sort(42)\n")

    def test_list_sort_comparator_signature(self):
        with self.assertRaisesRegex(CheckError, r"got func\(i32, i32\) -> bool"):
            run("func less(a: i32, b: i32) -> bool:\n"
                "    return a < b\n"
                "func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.sort(less)\n")

    def test_list_sort_comparator_element_types(self):
        with self.assertRaisesRegex(
                CheckError,
                r"func\(Item, Item\) -> i32, got func\(i32, i32\) -> i32"):
            run("struct Item:\n"
                "    key: i32\n"
                "func by_key(a: i32, b: i32) -> i32:\n"
                "    return a - b\n"
                "func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<Item>()\n"
                "    xs.sort(by_key)\n")

    def test_list_new_members_value_use_rejected(self):
        for member, msg in (('insert', r"'insert' must be called: xs\.insert\(i, v\)"),
                            ('remove', r"'remove' must be called: xs\.remove\(i\)"),
                            ('sort', r"'sort' must be called: xs\.sort\(cmp\)")):
            with self.assertRaisesRegex(CheckError, msg):
                run("func f() -> void:\n"
                    "    let a = Arena(4096)\n"
                    "    let xs = a.list::<i32>()\n"
                    f"    let f = xs.{member}\n")

    def test_list_unknown_method(self):
        with self.assertRaisesRegex(CheckError, "List has no method 'nope'"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    xs.nope()\n")

    def test_list_member_value_use_rejected(self):
        with self.assertRaisesRegex(CheckError, "'push' must be called"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    let p = xs.push\n")

    def test_list_at_value_use_rejected(self):
        with self.assertRaisesRegex(CheckError, "'at' must be called with an index"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let xs = a.list::<i32>()\n"
                "    let f = xs.at\n")

    def test_len_of_non_list(self):
        with self.assertRaisesRegex(CheckError, "len expects an array, a List, or a StrBuilder"):
            run("func f() -> void:\n"
                "    print_i32(len(1))\n")

    def test_list_as_function_param(self):
        run("func fill(xs: List<i32>):\n"
            "    xs.push(1)\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    fill(xs)\n")

    def test_list_handle_copy(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let xs = a.list::<i32>()\n"
            "    let ys = xs\n"
            "    ys.push(1)\n"
            "    print_i32(len(xs))\n")

    def test_list_of_lists(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let rows = a.list::<List<i32>>()\n"
            "    rows.push(a.list::<i32>())\n"
            "    rows.at(0).push(42)\n"
            "    rows.at(0).at(0) = 43\n"
            "    print_i32(rows[0].at(0))\n")

    def test_list_in_struct(self):
        run("struct Bag:\n    xs: List<i32>\n"
            "func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = Bag(xs: a.list::<i32>())\n"
            "    b.xs.push(1)\n"
            "    print_i32(len(b.xs))\n")

    def test_list_of_func_values(self):
        run("func inc(x: i32) -> i32:\n    return x + 1\n"
            "func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let gs = a.list::<func(i32) -> i32>()\n"
            "    gs.push(inc)\n"
            "    print_i32(gs.at(0)(41))\n")

    def test_strbuilder_create_and_type(self):
        run("func f() -> void:\n"
            "    let a = Arena(1024)\n"
            "    let b: StrBuilder = a.str_builder()\n"
            "    print_i32(len(b))\n")

    def test_strbuilder_takes_no_arguments(self):
        with self.assertRaisesRegex(CheckError, "takes no arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let b = a.str_builder(16)\n")

    def test_strbuilder_type_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "does not accept type arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(1024)\n"
                "    let b = a.str_builder::<i32>()\n")

    def test_strbuilder_ctor_hint(self):
        with self.assertRaisesRegex(CheckError, "a StrBuilder is created from an Arena"):
            run("func f() -> void:\n"
                "    let b = StrBuilder()\n")

    def test_strbuilder_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use type 'StrBuilder' as a value"):
            run("func f() -> void:\n"
                "    let x = StrBuilder\n")

    def test_strbuilder_duplicate_type_rejected(self):
        with self.assertRaisesRegex(CheckError, "duplicate type 'StrBuilder'"):
            run("struct StrBuilder:\n    x: i32\n")

    def test_strbuilder_append_and_to_str(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    b.append_str(\"hp \")\n"
            "    b.append_i32(42)\n"
            "    b.append_u32(7)\n"
            "    b.append_f32(1.5)\n"
            "    b.append_f64(2.5)\n"
            "    b.append_bool(true)\n"
            "    print_str(b.to_str())\n")

    def test_strbuilder_append_wrong_type(self):
        with self.assertRaises(CheckError):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.append_i32(\"nope\")\n")

    def test_strbuilder_append_arity(self):
        with self.assertRaisesRegex(CheckError, "'append_str' expects one value"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.append_str(\"a\", \"b\")\n")

    def test_strbuilder_append_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'append_i32' does not accept named arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.append_i32(v: 1)\n")

    def test_strbuilder_append_type_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "'append_i32' does not accept type arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.append_i32::<i32>(1)\n")

    def test_strbuilder_to_str_no_args(self):
        with self.assertRaisesRegex(CheckError, "'to_str' takes no arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    print_str(b.to_str(1))\n")

    def test_strbuilder_clear_no_args(self):
        with self.assertRaisesRegex(CheckError, "'clear' takes no arguments"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.clear(1)\n")

    def test_strbuilder_unknown_method(self):
        with self.assertRaisesRegex(CheckError, "StrBuilder has no method 'nope'"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    b.nope()\n")

    def test_strbuilder_method_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "'append_str' must be called"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    let g = b.append_str\n")

    def test_strbuilder_unknown_field(self):
        with self.assertRaisesRegex(CheckError, "no field 'huh'"):
            run("func f() -> void:\n"
                "    let a = Arena(4096)\n"
                "    let b = a.str_builder()\n"
                "    print_i32(b.huh)\n")

    def test_strbuilder_as_function_param(self):
        run("func note(b: StrBuilder):\n"
            "    b.append_str(\"note\")\n"
            "func main() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    note(b)\n"
            "    print_str(b.to_str())\n")

    def test_strbuilder_len(self):
        run("func f() -> void:\n"
            "    let a = Arena(4096)\n"
            "    let b = a.str_builder()\n"
            "    b.append_str(\"abc\")\n"
            "    print_i32(len(b))\n")

    def test_enum_declare_and_use(self):
        run("enum State:\n"
            "    Menu\n"
            "    Playing\n"
            "func f() -> void:\n"
            "    let s = State.Menu\n"
            "    if s == State.Playing:\n"
            "        print_str(\"playing\")\n")

    def test_enum_members_numbered_in_order(self):
        prog, tc = run("enum State:\n"
                       "    Menu\n"
                       "    Playing\n"
                       "    Paused\n"
                       "func f() -> void:\n"
                       "    let s = State.Menu\n")
        et = tc.enums['State']
        self.assertEqual(et.members, {'Menu': 0, 'Playing': 1, 'Paused': 2})

    def test_enum_explicit_values_and_auto_increment(self):
        prog, tc = run("enum E:\n"
                       "    A = 5\n"
                       "    B\n"
                       "    C = 2\n"
                       "    D\n")
        self.assertEqual(tc.enums['E'].members, {'A': 5, 'B': 6, 'C': 2, 'D': 3})

    def test_enum_duplicate_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "already used by 'B'"):
            run("enum E:\n"
                "    A = 2\n"
                "    B\n"
                "    C = 3\n")

    def test_enum_value_out_of_range_rejected(self):
        with self.assertRaisesRegex(CheckError, "outside the i32 range"):
            run("enum E:\n"
                "    A = 2147483648\n")

    def test_enum_payload_construct_and_match(self):
        run("struct Point:\n"
            "    x: i32\n"
            "    y: i32\n"
            "enum Shape:\n"
            "    Empty\n"
            "    Dot(Point)\n"
            "    Line(Point, Point)\n"
            "func f(s: Shape) -> i32:\n"
            "    match s:\n"
            "        Shape.Empty:\n"
            "            return 0\n"
            "        Shape.Dot(p):\n"
            "            return p.x\n"
            "        Shape.Line(a, b):\n"
            "            return a.x + b.y\n"
            "func main() -> void:\n"
            "    let p = Point(x: 1, y: 2)\n"
            "    print_i32(f(Shape.Line(p, p)))\n")

    def test_enum_payload_bare_member_rejected(self):
        with self.assertRaisesRegex(CheckError, "carries values; construct it"):
            run("enum E:\n"
                "    A(i32)\n"
                "func main() -> void:\n"
                "    let x = E.A\n")

    def test_enum_payload_wrong_arity_rejected(self):
        with self.assertRaisesRegex(CheckError, "expects 1 value\\(s\\), got 2"):
            run("enum E:\n"
                "    A(i32)\n"
                "func main() -> void:\n"
                "    let x = E.A(1, 2)\n")

    def test_enum_payload_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "do not accept named arguments"):
            run("enum E:\n"
                "    A(i32)\n"
                "func main() -> void:\n"
                "    let x = E.A(v: 1)\n")

    def test_enum_payload_match_arity_rejected(self):
        with self.assertRaisesRegex(CheckError, "expects 2 binding\\(s\\), got 1"):
            run("enum E:\n"
                "    A(i32, i32)\n"
                "func f(e: E) -> void:\n"
                "    match e:\n"
                "        E.A(x):\n"
                "            return\n")

    def test_enum_payload_multi_pattern_binding_rejected(self):
        with self.assertRaisesRegex(CheckError, "multiple patterns cannot bind"):
            run("enum E:\n"
                "    A(i32)\n"
                "    B\n"
                "func f(e: E) -> void:\n"
                "    match e:\n"
                "        E.A(x), E.B:\n"
                "            print_i32(x)\n")

    def test_enum_payload_wildcard_ok(self):
        run("enum E:\n"
            "    A(i32)\n"
            "    B\n"
            "func f(e: E) -> void:\n"
            "    match e:\n"
            "        E.A(_):\n"
            "            return\n"
            "        E.B():\n"
            "            return\n")

    def test_enum_payload_extern_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use payload enum 'E'"):
            run("enum E:\n"
                "    A(i32)\n"
                "extern \"c\" {\n"
                "    func f(e: E) -> void\n"
                "}\n")

    def test_enum_payload_noncopyable_rejected(self):
        with self.assertRaisesRegex(CheckError, "must be copyable and non-void"):
            run("enum E:\n"
                "    A(Arena)\n")

    def test_enum_payload_equality_ok(self):
        run("struct Point:\n"
            "    x: i32\n"
            "enum E:\n"
            "    A(Point)\n"
            "    B(str)\n"
            "func main() -> void:\n"
            "    let p = Point(x: 1)\n"
            "    print_bool(E.A(p) == E.A(p))\n"
            "    print_bool(E.B(\"x\") == E.B(\"x\"))\n")

    def test_enum_payload_without_equality_rejected(self):
        with self.assertRaisesRegex(CheckError, "payload 'A\\[0\\]' \\(Matrix4\\) has no equality"):
            run("enum E:\n"
                "    A(Matrix4)\n"
                "func f(e: E) -> bool:\n"
                "    return e == E.A(translation(0.0, 0.0, 0.0))\n")

    def test_enum_payload_duplicate_binding_rejected(self):
        with self.assertRaisesRegex(CheckError, "duplicate binding 'x'"):
            run("enum E:\n"
                "    A(i32, i32)\n"
                "func f(e: E) -> void:\n"
                "    match e:\n"
                "        E.A(x, x):\n"
                "            return\n")

    def test_enum_payload_reserved_tag_name_rejected(self):
        with self.assertRaisesRegex(CheckError, "reserved in payload enums"):
            run("enum E:\n"
                "    A(i32)\n"
                "    VantaTag\n")

    def test_enum_payload_type_must_be_declared_first(self):
        with self.assertRaisesRegex(CheckError, "unknown type 'Later'"):
            run("enum E:\n"
                "    A(Later)\n"
                "struct Later:\n"
                "    x: i32\n")

    def test_enum_in_struct_and_signatures(self):
        run("enum Mode:\n"
            "    Off\n"
            "    On\n"
            "struct Lamp:\n"
            "    mode: Mode\n"
            "func toggle(m: Mode) -> Mode:\n"
            "    if m == Mode.On:\n"
            "        return Mode.Off\n"
            "    return Mode.On\n"
            "func main() -> void:\n"
            "    let l = Lamp(mode: Mode.Off)\n"
            "    print_i32(enum_to_i32(toggle(l.mode)))\n")

    def test_enum_inequality(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func main() -> void:\n"
            "    let a = State.A\n"
            "    let b = State.B\n"
            "    if a != b and a == State.A:\n"
            "        print_str(\"ok\")\n")

    def test_enum_in_array(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func main() -> void:\n"
            "    let xs: [State, 2] = [State.A, State.B]\n"
            "    if xs.at(1) == State.B:\n"
            "        print_str(\"b\")\n")

    def test_enum_in_list(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func main() -> void:\n"
            "    let arena = Arena(4096)\n"
            "    let xs = arena.list::<State>()\n"
            "    xs.push(State.A)\n"
            "    xs.push(State.B)\n"
            "    if xs.at(0) == State.A:\n"
            "        print_str(\"a\")\n"
            "    print_i32(len(xs))\n")

    def test_enum_rebind_requires_mut(self):
        with self.assertRaisesRegex(CheckError, "invalid assignment target"):
            run("enum State:\n"
                "    A\n"
                "    B\n"
                "func main() -> void:\n"
                "    let s = State.A\n"
                "    s = State.B\n")

    def test_enum_mut_rebind(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func main() -> void:\n"
            "    mut s = State.A\n"
            "    s = State.B\n"
            "    print_i32(enum_to_i32(s))\n")

    def test_enum_unknown_member(self):
        with self.assertRaisesRegex(CheckError, "enum 'State' has no member 'Purple'"):
            run("enum State:\n"
                "    Menu\n"
                "func main() -> void:\n"
                "    let s = State.Purple\n")

    def test_enum_ordering_rejected(self):
        with self.assertRaisesRegex(CheckError, "ordering comparisons are not supported on State"):
            run("enum State:\n"
                "    A\n"
                "    B\n"
                "func main() -> void:\n"
                "    if State.A < State.B:\n"
                "        print_str(\"x\")\n")

    def test_enum_compare_mismatched_enums_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot compare A and B"):
            run("enum A:\n"
                "    X\n"
                "enum B:\n"
                "    Y\n"
                "func main() -> void:\n"
                "    if A.X == B.Y:\n"
                "        print_str(\"x\")\n")

    def test_enum_compare_with_int_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot compare State and <int-lit>"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let s = State.A\n"
                "    if s == 1:\n"
                "        print_str(\"x\")\n")

    def test_enum_wrong_initializer_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot assign <int-lit> to State"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let s: State = 1\n")

    def test_enum_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use type 'State' as a value"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let x = State\n")

    def test_enum_construction_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot construct 'State'"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let x = State(1)\n")

    def test_enum_member_on_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "enum values have no fields; write State.Member"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let s = State.A\n"
                "    let x = s.A\n")

    def test_enum_duplicate_member(self):
        with self.assertRaisesRegex(CheckError, "duplicate member 'Menu'"):
            run("enum State:\n"
                "    Menu\n"
                "    Menu\n")

    def test_enum_duplicate_type(self):
        with self.assertRaisesRegex(CheckError, "duplicate type 'State'"):
            run("enum State:\n    A\n"
                "enum State:\n    B\n")

    def test_enum_struct_collision(self):
        with self.assertRaisesRegex(CheckError, "duplicate type 'State'"):
            run("struct State:\n    x: i32\n"
                "enum State:\n    A\n")

    def test_enum_func_collision(self):
        with self.assertRaisesRegex(CheckError, "function name 'State' collides with type"):
            run("enum State:\n    A\n"
                "func State() -> void:\n    print_str(\"x\")\n")

    def test_type_after_func_collision(self):
        with self.assertRaisesRegex(CheckError, "type name 'State' collides with function"):
            run("func State() -> void:\n    print_str(\"x\")\n"
                "enum State:\n    A\n")

    def test_struct_after_func_collision(self):
        with self.assertRaisesRegex(CheckError, "type name 'P' collides with function"):
            run("func P() -> void:\n    print_str(\"x\")\n"
                "struct P:\n    x: i32\n")

    def test_enum_const_collision(self):
        with self.assertRaisesRegex(CheckError, "constant 'State' collides with type"):
            run("enum State:\n    A\n"
                "const State = 5\n")

    def test_enum_reserved_type_names(self):
        with self.assertRaisesRegex(CheckError, "'List' is a reserved built-in type name"):
            run("enum List:\n    A\n")
        with self.assertRaisesRegex(CheckError, "reserved for generated function-pointer aliases"):
            run("enum FnPtr0:\n    A\n")

    def test_enum_to_i32(self):
        run("enum State:\n"
            "    A\n"
            "func main() -> void:\n"
            "    let n: i32 = enum_to_i32(State.A)\n")

    def test_enum_to_i32_wrong_arg(self):
        with self.assertRaisesRegex(CheckError, "enum_to_i32 expects an enum value, got <int-lit>"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    print_i32(enum_to_i32(3))\n")

    def test_enum_to_i32_arity(self):
        with self.assertRaisesRegex(CheckError, "enum_to_i32 takes one argument, got 2"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    print_i32(enum_to_i32(State.A, State.A))\n")

    def test_enum_to_i32_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'enum_to_i32' as a value"):
            run("enum State:\n"
                "    A\n"
                "func main() -> void:\n"
                "    let f = enum_to_i32\n")

    def test_enum_in_extern_ok(self):
        run("enum Mode:\n"
            "    On\n"
            "    Off\n"
            "extern \"c\" {\n"
            "    func set_mode(m: Mode) -> Mode\n"
            "    func watch(m: ptr<Mode>) -> void\n"
            "    func all(xs: List<Mode>) -> void\n"
            "}\n")

    def test_enum_in_extern_match_ok(self):
        run("enum Mode:\n"
            "    On\n"
            "    Off\n"
            "extern \"c\" {\n"
            "    func get_mode() -> Mode\n"
            "}\n"
            "func main() -> void:\n"
            "    match get_mode():\n"
            "        Mode.On:\n"
            "            print_str(\"on\")\n"
            "        Mode.Off:\n"
            "            print_str(\"off\")\n")

    def test_enum_to_i32_extern_ok(self):
        run("enum Mode:\n"
            "    On\n"
            "extern \"c\" {\n"
            "    func set_mode(m: i32) -> void\n"
            "}\n"
            "func main() -> void:\n"
            "    set_mode(enum_to_i32(Mode.On))\n")

    def test_match_exhaustive_ok(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func f(s: State) -> i32:\n"
            "    match s:\n"
            "        State.A:\n"
            "            return 1\n"
            "        State.B:\n"
            "            return 2\n")

    def test_match_else_ok(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func f(s: State) -> i32:\n"
            "    match s:\n"
            "        State.A:\n"
            "            return 1\n"
            "        else:\n"
            "            return 0\n")

    def test_match_else_only_ok(self):
        run("enum State:\n"
            "    A\n"
            "func f(s: State) -> void:\n"
            "    match s:\n"
            "        else:\n"
            "            print_str(\"x\")\n")

    def test_match_multi_pattern_arm_ok(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "    C\n"
            "func f(s: State) -> i32:\n"
            "    match s:\n"
            "        State.A, State.B:\n"
            "            return 1\n"
            "        State.C:\n"
            "            return 2\n")

    def test_match_on_field_and_call_ok(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "struct G:\n"
            "    state: State\n"
            "func pick() -> State:\n"
            "    return State.A\n"
            "func f(g: G) -> i32:\n"
            "    match g.state:\n"
            "        State.A:\n"
            "            return 1\n"
            "        else:\n"
            "            return 0\n"
            "func h() -> i32:\n"
            "    match pick():\n"
            "        State.A:\n"
            "            return 1\n"
            "        else:\n"
            "            return 0\n")

    def test_match_break_and_continue_in_loop_ok(self):
        run("enum State:\n"
            "    A\n"
            "    B\n"
            "func f(s: State) -> void:\n"
            "    for i in range(0, 3):\n"
            "        match s:\n"
            "            State.A:\n"
            "                continue\n"
            "            else:\n"
            "                break\n")

    def test_match_break_outside_loop_rejected(self):
        with self.assertRaisesRegex(CheckError, "'break' outside loop"):
            run("enum State:\n"
                "    A\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.A:\n"
                "            break\n"
                "        else:\n"
                "            return\n")

    def test_match_non_enum_rejected(self):
        with self.assertRaisesRegex(CheckError, "match expects an enum value, got <int-lit>"):
            run("func f() -> void:\n"
                "    match 3:\n"
                "        else:\n"
                "            return\n")

    def test_match_wrong_enum_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot match Mode.On against 'State'"):
            run("enum State:\n"
                "    A\n"
                "enum Mode:\n"
                "    On\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        Mode.On:\n"
                "            return\n"
                "        else:\n"
                "            return\n")

    def test_match_unknown_member_rejected(self):
        with self.assertRaisesRegex(CheckError, "enum 'State' has no member 'Purple'"):
            run("enum State:\n"
                "    A\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.Purple:\n"
                "            return\n"
                "        else:\n"
                "            return\n")

    def test_match_duplicate_arm_rejected(self):
        with self.assertRaisesRegex(CheckError, "duplicate match arm 'State.A'"):
            run("enum State:\n"
                "    A\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.A:\n"
                "            return\n"
                "        State.A:\n"
                "            return\n"
                "        else:\n"
                "            return\n")

    def test_match_missing_member_rejected(self):
        with self.assertRaisesRegex(
                CheckError,
                "match on 'State' is missing member 'B'; add an arm or an else branch"):
            run("enum State:\n"
                "    A\n"
                "    B\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.A:\n"
                "            return\n")

    def test_match_missing_members_rejected(self):
        with self.assertRaisesRegex(
                CheckError,
                "match on 'State' is missing members 'B', 'C'"):
            run("enum State:\n"
                "    A\n"
                "    B\n"
                "    C\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.A:\n"
                "            return\n")

    def test_match_arm_locals_scoped(self):
        with self.assertRaises(CheckError):
            run("enum State:\n"
                "    A\n"
                "func f(s: State) -> void:\n"
                "    match s:\n"
                "        State.A:\n"
                "            let x = 1\n"
                "        else:\n"
                "            return\n"
                "    print_i32(x)\n")

    def test_ptr_void_widening_in_argument(self):
        run("func take(p: ptr<void>) -> void:\n"
            "    print_str(\"ok\")\n"
            "func main() -> void:\n"
            "    let a = Arena(256)\n"
            "    let xs = a.alloc::<i32>(4)\n"
            "    take(xs)\n")

    def test_ptr_void_widening_in_return(self):
        run("func wrap(p: ptr<i32>) -> ptr<void>:\n"
            "    return p\n"
            "func main() -> void:\n"
            "    let a = Arena(256)\n"
            "    let xs = a.alloc::<i32>(1)\n"
            "    let w = wrap(xs)\n"
            "    print_bool(ptr_is_null(w))\n")

    def test_ptr_widening_only_to_void(self):
        with self.assertRaisesRegex(CheckError, "cannot assign ptr<i32> to ptr<f32>"):
            run("func take(p: ptr<f32>) -> void:\n"
                "    print_str(\"x\")\n"
                "func main() -> void:\n"
                "    let a = Arena(256)\n"
                "    let xs = a.alloc::<i32>(4)\n"
                "    take(xs)\n")

    def test_ptr_void_not_narrowed_to_typed(self):
        with self.assertRaisesRegex(CheckError, "cannot assign ptr<void> to ptr<i32>"):
            run("extern \"c\" {\n"
                "    func mk() -> ptr<void>\n"
                "}\n"
                "func take(p: ptr<i32>) -> void:\n"
                "    print_str(\"x\")\n"
                "func main() -> void:\n"
                "    take(mk())\n")

    def test_ptr_void_cannot_be_indexed(self):
        with self.assertRaisesRegex(CheckError, "cannot index a ptr<void>"):
            run("extern \"c\" {\n"
                "    func mk() -> ptr<void>\n"
                "}\n"
                "func main() -> void:\n"
                "    let p = mk()\n"
                "    print_i32(p[0])\n")

    def test_alloc_void_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot allocate void"):
            run("func main() -> void:\n"
                "    let a = Arena(256)\n"
                "    let xs = a.alloc::<void>(1)\n")

    def test_ptr_is_null(self):
        run("func main() -> void:\n"
            "    let a = Arena(256)\n"
            "    let xs = a.alloc::<i32>(1)\n"
            "    if ptr_is_null(xs):\n"
            "        print_str(\"null\")\n")

    def test_ptr_is_null_on_ptr_void(self):
        run("extern \"c\" {\n"
            "    func mk() -> ptr<void>\n"
            "}\n"
            "func main() -> void:\n"
            "    if not ptr_is_null(mk()):\n"
            "        print_str(\"got\")\n")

    def test_ptr_is_null_on_function_value(self):
        run("func sq(x: i32) -> i32:\n"
            "    return x\n"
            "func main() -> void:\n"
            "    let f = sq\n"
            "    print_bool(ptr_is_null(f))\n")

    def test_ptr_is_null_wrong_arg(self):
        with self.assertRaisesRegex(
                CheckError,
                "ptr_is_null expects a pointer or a function value, got <int-lit>"):
            run("func main() -> void:\n"
                "    print_bool(ptr_is_null(3))\n")

    def test_ptr_is_null_arity(self):
        with self.assertRaisesRegex(CheckError, "ptr_is_null takes one argument, got 2"):
            run("func main() -> void:\n"
                "    let a = Arena(256)\n"
                "    let xs = a.alloc::<i32>(1)\n"
                "    print_bool(ptr_is_null(xs, xs))\n")

    def test_ptr_is_null_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'ptr_is_null' as a value"):
            run("func main() -> void:\n"
                "    let f = ptr_is_null\n")

    def test_ptr_mut_rebind(self):
        run("extern \"c\" {\n"
            "    func mk() -> ptr<void>\n"
            "}\n"
            "func main() -> void:\n"
            "    mut p = mk()\n"
            "    p = mk()\n"
            "    print_bool(ptr_is_null(p))\n")

    def test_ptr_rebind_requires_mut(self):
        with self.assertRaisesRegex(CheckError, "invalid assignment target"):
            run("extern \"c\" {\n"
                "    func mk() -> ptr<void>\n"
                "}\n"
                "func main() -> void:\n"
                "    let p = mk()\n"
                "    p = mk()\n")

    # ---------- narrow integers (v0.17.0) ----------

    def test_narrow_literals_ok(self):
        run("struct P:\n"
            "    a: i8\n"
            "    b: u8\n"
            "    c: i16\n"
            "    d: u16\n"
            "func main() -> void:\n"
            "    let p = P(a: -128, b: 255, c: -32768, d: 65535)\n"
            "    print_i32(p.a + p.b + p.c + p.d)\n")

    def test_narrow_literal_out_of_range_u8(self):
        with self.assertRaisesRegex(CheckError, "initializer: value 300 out of range for u8"):
            run("func f() -> void:\n    let x: u8 = 300\n")

    def test_narrow_literal_negative_unsigned(self):
        with self.assertRaisesRegex(CheckError, "initializer: value -1 out of range for u8"):
            run("func f() -> void:\n    let x: u8 = -1\n")

    def test_narrow_literal_out_of_range_i8(self):
        with self.assertRaisesRegex(CheckError, "initializer: value -129 out of range for i8"):
            run("func f() -> void:\n    let x: i8 = -129\n")

    def test_narrow_literal_out_of_range_u16(self):
        with self.assertRaisesRegex(CheckError, "initializer: value 65536 out of range for u16"):
            run("func f() -> void:\n    let x: u16 = 65536\n")

    def test_narrow_binop_literal_out_of_range(self):
        with self.assertRaisesRegex(CheckError, "value 300 out of range for u8"):
            run("func f() -> void:\n"
                "    let a: u8 = 1\n"
                "    if a == 300:\n"
                "        print_i32(1)\n")

    def test_narrow_float_literal_rejected(self):
        with self.assertRaisesRegex(CheckError, "initializer: cannot assign <float-lit> to u8"):
            run("func f() -> void:\n    let x: u8 = 5.0\n")

    def test_narrow_truncating_store_ok(self):
        run("func f(x: i32, y: u32) -> void:\n"
            "    mut a: u8 = x\n"
            "    a = x\n"
            "    let b: i16 = y\n"
            "    let c: u16 = a\n"
            "    print_i32(a)\n"
            "    print_i32(b)\n"
            "    print_i32(c)\n")

    def test_narrow_promotes_to_i32(self):
        run("func f(a: u8, b: i16, c: u16) -> void:\n"
            "    let s: i32 = a + b\n"
            "    let w: u32 = c\n"
            "    let n: i32 = -a\n"
            "    print_i32(s)\n"
            "    print_u32(w)\n"
            "    print_i32(n)\n"
            "    print_fmt(\"{} {} {}\", a, b, c)\n")

    def test_narrow_mixed_with_i32_ok(self):
        run("func f(a: u8, b: i32) -> void:\n"
            "    let s = a + b\n"
            "    if a < b:\n"
            "        print_i32(s)\n")

    def test_narrow_index_and_range_ok(self):
        run("func f(p: ptr<i32>, i: u8, c: u16) -> void:\n"
            "    print_i32(p[i])\n"
            "    for k in range(c, 3):\n"
            "        print_i32(k)\n")

    def test_narrow_const_ok(self):
        run("const MAX: u8 = 200\n"
            "func f() -> void:\n"
            "    let x: u8 = MAX\n"
            "    print_i32(x)\n")

    def test_narrow_in_list_ok(self):
        run("func f(x: i32) -> void:\n"
            "    let a = Arena(256)\n"
            "    let xs = a.list::<u8>()\n"
            "    xs.push(x)\n"
            "    xs.push(4)\n"
            "    print_i32(xs.at(0))\n")

    # ---------- ptr_cast (v0.17.0) ----------

    def test_ptr_cast_ok(self):
        run("struct P:\n"
            "    x: i32\n"
            "func f(p: ptr<void>, q: ptr<i32>) -> void:\n"
            "    let a = ptr_cast::<i32>(p)\n"
            "    let b = ptr_cast::<P>(p)\n"
            "    let c = ptr_cast::<void>(q)\n"
            "    print_i32(a[0])\n"
            "    print_i32(b[0].x)\n")

    def test_ptr_cast_requires_type_argument(self):
        with self.assertRaisesRegex(CheckError,
                r"ptr_cast requires a type argument: ptr_cast::<T>\(p\)"):
            run("func f(p: ptr<void>) -> void:\n    let q = ptr_cast(p)\n")

    def test_ptr_cast_function_target_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_cast cannot target a function type"):
            run("func f(p: ptr<void>) -> void:\n"
                "    let q = ptr_cast::<func(i32) -> i32>(p)\n")

    def test_ptr_cast_non_pointer_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_cast expects a pointer, got i32"):
            run("func f(x: i32) -> void:\n    let q = ptr_cast::<i32>(x)\n")

    def test_ptr_cast_arity(self):
        with self.assertRaisesRegex(CheckError, "ptr_cast takes one argument, got 2"):
            run("func f(p: ptr<void>) -> void:\n    let q = ptr_cast::<i32>(p, p)\n")

    def test_ptr_cast_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_cast does not accept named arguments"):
            run("func f(p: ptr<void>) -> void:\n    let q = ptr_cast::<i32>(x: p)\n")

    def test_ptr_cast_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'ptr_cast' as a value"):
            run("func f() -> void:\n    let q = ptr_cast\n")

    # ---------- ptr_offset (v0.18.0) ----------

    def test_ptr_offset_ok(self):
        run("func f(p: ptr<i32>, n: i32) -> void:\n"
            "    let a = ptr_offset(p, n)\n"
            "    let b = ptr_offset(p, 0)\n"
            "    let c = ptr_offset(a, -2)\n"
            "    let d: ptr<i32> = ptr_offset(a, 1)\n")

    def test_ptr_offset_narrow_offset_ok(self):
        # Reading a narrow value yields i32, so it is a fine offset.
        run("func f(p: ptr<i32>, n: u8) -> void:\n"
            "    let a = ptr_offset(p, n)\n")

    def test_ptr_offset_requires_pointer(self):
        with self.assertRaisesRegex(CheckError, "ptr_offset expects a pointer, got i32"):
            run("func f(x: i32) -> void:\n    let p = ptr_offset(x, 1)\n")

    def test_ptr_offset_void_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot offset a ptr<void>"):
            run("func f(p: ptr<void>) -> void:\n    let q = ptr_offset(p, 1)\n")

    def test_ptr_offset_type_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_offset does not accept type arguments"):
            run("func f(p: ptr<i32>) -> void:\n    let q = ptr_offset::<i32>(p, 1)\n")

    def test_ptr_offset_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_offset does not accept named arguments"):
            run("func f(p: ptr<i32>) -> void:\n    let q = ptr_offset(p, x: 1)\n")

    def test_ptr_offset_arity(self):
        with self.assertRaisesRegex(CheckError, "ptr_offset takes two arguments, got 1"):
            run("func f(p: ptr<i32>) -> void:\n    let q = ptr_offset(p)\n")

    def test_ptr_offset_float_offset_rejected(self):
        with self.assertRaisesRegex(CheckError, "offset: cannot assign f32 to i32"):
            run("func f(p: ptr<i32>, n: f32) -> void:\n    let q = ptr_offset(p, n)\n")

    def test_ptr_offset_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'ptr_offset' as a value"):
            run("func f() -> void:\n    let q = ptr_offset\n")

    # ---------- ptr_null (v0.19.0) ----------

    def test_ptr_null_ok(self):
        run("func f() -> void:\n"
            "    let a = ptr_null::<i32>()\n"
            "    let b = ptr_null::<void>()\n"
            "    let c: ptr<f32> = ptr_null::<f32>()\n"
            "    let d = ptr_null::<Vec2>()\n")

    def test_ptr_null_nested_pointer_ok(self):
        run("func f() -> void:\n"
            "    let pp = ptr_null::<ptr<i32>>()\n")

    def test_ptr_null_func_type_ok(self):
        # A null of a function type: the empty callback slot a queue-mode
        # device passes to C.
        run("struct S:\n"
            "    cb: func(i32) -> i32\n"
            "    n: i32\n"
            "func f() -> void:\n"
            "    let s = S(cb: ptr_null::<func(i32) -> i32>(), n: 1)\n")

    def test_ptr_null_requires_type_argument(self):
        with self.assertRaisesRegex(
                CheckError, r"ptr_null requires a type argument: ptr_null::<T>\(\)"):
            run("func f() -> void:\n    let p = ptr_null()\n")

    def test_ptr_null_arity(self):
        with self.assertRaisesRegex(CheckError, "ptr_null takes no arguments, got 1"):
            run("func f() -> void:\n    let p = ptr_null::<i32>(5)\n")

    def test_ptr_null_named_args_rejected(self):
        with self.assertRaisesRegex(CheckError, "ptr_null does not accept named arguments"):
            run("func f() -> void:\n    let p = ptr_null::<i32>(x: 1)\n")

    def test_ptr_null_as_value_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot use builtin 'ptr_null' as a value"):
            run("func f() -> void:\n    let p = ptr_null\n")

    # ---------- for-each (v0.17.0) ----------

    def test_foreach_list_ok(self):
        run("func f(xs: List<i32>) -> void:\n"
            "    for x in xs:\n"
            "        print_i32(x * 2)\n")

    def test_foreach_array_ok(self):
        run("func f() -> void:\n"
            "    let grid = [1, 2, 3]\n"
            "    for v in grid:\n"
            "        print_i32(v)\n"
            "    for v in [4, 5]:\n"
            "        print_i32(v)\n")

    def test_foreach_element_type(self):
        run("struct P:\n"
            "    x: i32\n"
            "func f(xs: List<P>, names: [str, 2]) -> void:\n"
            "    for p in xs:\n"
            "        print_i32(p.x)\n"
            "    for s in names:\n"
            "        print_str(s)\n")

    def test_foreach_non_iterable_rejected(self):
        with self.assertRaisesRegex(CheckError,
                r"cannot iterate over i32; for-each supports arrays and Lists"):
            run("func f(x: i32) -> void:\n"
                "    for v in x:\n"
                "        print_i32(v)\n")

    def test_foreach_pointer_rejected(self):
        with self.assertRaisesRegex(CheckError, r"cannot iterate over ptr<i32>"):
            run("func f(p: ptr<i32>) -> void:\n"
                "    for v in p:\n"
                "        print_i32(v)\n")

    def test_foreach_loop_var_immutable(self):
        with self.assertRaisesRegex(CheckError, "invalid assignment target"):
            run("func f(xs: List<i32>) -> void:\n"
                "    for v in xs:\n"
                "        v = 1\n")

    def test_foreach_break_continue_ok(self):
        run("func f(xs: List<i32>) -> void:\n"
            "    for v in xs:\n"
            "        if v == 1:\n"
            "            continue\n"
            "        if v == 9:\n"
            "            break\n"
            "        print_i32(v)\n")

    # ---------- struct equality (v0.17.0) ----------

    def test_struct_eq_ok(self):
        run("enum M:\n"
            "    A\n"
            "    B\n"
            "struct Inner:\n"
            "    q: str\n"
            "    v: Vec2\n"
            "struct S:\n"
            "    n: i32\n"
            "    m: M\n"
            "    flags: [bool, 2]\n"
            "    inner: Inner\n"
            "func f(a: S, b: S) -> void:\n"
            "    if a == b:\n"
            "        print_str(\"same\")\n"
            "    if a != b:\n"
            "        print_str(\"diff\")\n")

    def test_struct_eq_ptr_field_rejected(self):
        with self.assertRaisesRegex(CheckError,
                r"cannot compare struct 'Q' with '==': field 'p' \(ptr<i32>\) has no equality"):
            run("struct Q:\n"
                "    p: ptr<i32>\n"
                "func f(a: Q, b: Q) -> void:\n"
                "    if a == b:\n"
                "        print_i32(1)\n")

    def test_struct_eq_func_field_ok(self):
        run("struct Q:\n"
            "    cb: func(i32) -> i32\n"
            "func inc(x: i32) -> i32:\n"
            "    return x + 1\n"
            "func f(a: Q, b: Q) -> void:\n"
            "    if a != b:\n"
            "        print_i32(1)\n"
            "func g() -> void:\n"
            "    f(Q(cb: inc), Q(cb: inc))\n")

    def test_struct_eq_list_field_rejected(self):
        with self.assertRaisesRegex(CheckError,
                r"cannot compare struct 'Q' with '==': field 'xs' \(List<i32>\) has no equality"):
            run("struct Q:\n"
                "    xs: List<i32>\n"
                "func f(a: Q, b: Q) -> void:\n"
                "    if a == b:\n"
                "        print_i32(1)\n")

    def test_struct_eq_nested_blocker_path(self):
        with self.assertRaisesRegex(CheckError,
                r"field 'inner\.p' \(ptr<i32>\) has no equality"):
            run("struct Inner:\n"
                "    p: ptr<i32>\n"
                "struct Outer:\n"
                "    name: str\n"
                "    inner: Inner\n"
                "func f(a: Outer, b: Outer) -> void:\n"
                "    if a == b:\n"
                "        print_i32(1)\n")

    def test_struct_eq_array_blocker_path(self):
        with self.assertRaisesRegex(CheckError,
                r"field 'cells\[N\]' \(ptr<i32>\) has no equality"):
            run("struct S:\n"
                "    cells: [ptr<i32>, 3]\n"
                "func f(a: S, b: S) -> void:\n"
                "    if a == b:\n"
                "        print_i32(1)\n")

    def test_struct_eq_quat_still_rejected(self):
        with self.assertRaisesRegex(CheckError, "cannot compare Quat and Quat with '=='"):
            run("func f() -> void:\n"
                "    let a = Quat()\n"
                "    let b = Quat()\n"
                "    if a == b:\n"
                "        print_i32(1)\n")

    # ---------- generic enums (v0.31.0) ----------

    def test_generic_enum_infers_from_payload(self):
        prog, tc = run("enum Option<T>:\n"
                       "    None\n"
                       "    Some(T)\n"
                       "func main() -> void:\n"
                       "    let value = Option.Some(5)\n")
        decl = prog.decls[1].body[0]
        self.assertEqual(repr(decl.var_type), 'Option<i32>')
        self.assertEqual(repr(tc.enums[decl.var_type.name]), 'Option<i32>')

    def test_generic_enum_none_uses_annotation(self):
        run("enum Option<T>:\n"
            "    None\n"
            "    Some(T)\n"
            "func main() -> void:\n"
            "    let value: Option<i32> = Option.None\n"
            "    match value:\n"
            "        Option.None:\n"
            "            print_i32(0)\n"
            "        Option.Some(v):\n"
            "            print_i32(v)\n")

    def test_generic_result_constructors_use_return_type(self):
        run("enum Result<T, E>:\n"
            "    Ok(T)\n"
            "    Err(E)\n"
            "func parse(n: i32) -> Result<i32, str>:\n"
            "    if n < 0:\n"
            "        return Result.Err(\"negative\")\n"
            "    return Result.Ok(n)\n")

    def test_generic_enum_explicit_type_arguments(self):
        prog, tc = run("enum Result<T, E>:\n"
                       "    Ok(T)\n"
                       "    Err(E)\n"
                       "func main() -> void:\n"
                       "    let ok = Result.Ok::<i32, str>(5)\n"
                       "    let err = Result.Err::<i32, str>(\"bad\")\n")
        self.assertEqual(repr(prog.decls[1].body[0].var_type), 'Result<i32, str>')
        self.assertEqual(repr(prog.decls[1].body[1].var_type), 'Result<i32, str>')

    def test_generic_enum_missing_inference_reports_parameter(self):
        with self.assertRaisesRegex(
                CheckError, "cannot infer type parameter 'E' for 'Result.Ok'"):
            run("enum Result<T, E>:\n"
                "    Ok(T)\n"
                "    Err(E)\n"
                "func main() -> void:\n"
                "    let value = Result.Ok(5)\n")

    def test_generic_enum_wrong_type_argument_count(self):
        with self.assertRaisesRegex(
                CheckError, "expects 1 type argument\\(s\\) <T>, got 2"):
            run("enum Option<T>:\n"
                "    None\n"
                "    Some(T)\n"
                "func main() -> void:\n"
                "    let value: Option<i32, str> = Option.None\n")

    def test_generic_enum_family_requires_arguments(self):
        with self.assertRaisesRegex(
                CheckError, "generic type 'Option' requires type arguments"):
            run("enum Option<T>:\n"
                "    None\n"
                "func f(value: Option) -> void:\n"
                "    return\n")

    def test_generic_enum_nested_match(self):
        run("enum Option<T>:\n"
            "    None\n"
            "    Some(T)\n"
            "func unwrap(value: Option<Option<i32>>) -> i32:\n"
            "    match value:\n"
            "        Option.None:\n"
            "            return -1\n"
            "        Option.Some(inner):\n"
            "            match inner:\n"
            "                Option.None:\n"
            "                    return 0\n"
            "                Option.Some(v):\n"
            "                    return v\n")

    def test_generic_enum_expected_type_from_struct_field(self):
        run("enum Option<T>:\n"
            "    None\n"
            "    Some(T)\n"
            "struct Holder:\n"
            "    value: Option<i32>\n"
            "func main() -> void:\n"
            "    let holder = Holder(value: Option.None)\n"
            "    print_bool(holder.value == Option.None)\n")

    def test_generic_enum_expected_type_from_list_push(self):
        run("enum Option<T>:\n"
            "    None\n"
            "    Some(T)\n"
            "func main() -> void:\n"
            "    let arena = Arena(1024)\n"
            "    let values = arena.list::<Option<i32>>()\n"
            "    values.push(Option.None)\n"
            "    values.push(Option.Some(3))\n")

    def test_generic_enum_expected_type_from_comparison(self):
        run("enum Option<T>:\n"
            "    None\n"
            "    Some(T)\n"
            "enum Result<T, E>:\n"
            "    Ok(T)\n"
            "    Err(E)\n"
            "func main() -> void:\n"
            "    let value: Result<i32, str> = Result.Ok(3)\n"
            "    if value == Result.Ok(3):\n"
            "        print_i32(1)\n"
            "    if Result.Err(\"bad\") != value:\n"
            "        print_i32(2)\n"
            "    if Option.None == Option.Some(3):\n"
            "        print_i32(3)\n"
            "    if Option.Some(3) != Option.None:\n"
            "        print_i32(4)\n")

    def test_generic_enum_recursive_instantiation_rejected(self):
        with self.assertRaisesRegex(
                CheckError, "recursive generic enum instantiation"):
            run("enum Seq<T>:\n"
                "    Nil\n"
                "    Cons(T, Seq<T>)\n"
                "func main() -> void:\n"
                "    let value: Seq<i32> = Seq.Nil\n")

    def test_generic_enum_noncopyable_argument_rejected(self):
        with self.assertRaisesRegex(
                CheckError, "must be copyable and non-void"):
            run("enum Box<T>:\n"
                "    Empty\n"
                "    Value(T)\n"
                "func main() -> void:\n"
                "    let value: Box<Arena> = Box.Empty\n")

    def test_generic_enum_reserved_type_parameter(self):
        with self.assertRaisesRegex(
                CheckError, "type parameter name 'i32' is reserved"):
            run("enum Bad<i32>:\n"
                "    A\n")


    def test_binop_int_overflow_raises(self):
        with self.assertRaisesRegex(CheckError, 'integer overflow'):
            run("func main() -> i32:\n    let x: i32 = 2000000000 + 2000000000\n")

    def test_arithmetic_division_by_zero_raises(self):
        with self.assertRaisesRegex(CheckError, 'division by zero'):
            run("func main() -> i32:\n    let x: i32 = 1 / 0\n")

    def test_generic_struct_instantiates_from_annotation(self):
        _, tc = run("struct Pair<T, U>:\n"
                    "    left: T\n"
                    "    right: U\n"
                    "func main() -> void:\n"
                    "    let p: Pair<i32, str> = "
                    "Pair(left: 1, right: \"x\")\n")
        self.assertIn('Pair__g0', tc.structs)

    def test_generic_struct_infers_from_arguments(self):
        _, tc = run("struct Pair<T, U>:\n"
                    "    left: T\n"
                    "    right: U\n"
                    "func main() -> void:\n"
                    "    let p = Pair(left: 1, right: 2.5)\n"
                    "    print_i32(p.left)\n")
        st = next(s for n, s in tc.structs.items()
                  if n.startswith('Pair__g'))
        self.assertEqual(repr(st.fields['left']), 'i32')
        self.assertEqual(repr(st.fields['right']), 'f32')

    def test_generic_struct_two_instances_are_distinct(self):
        _, tc = run("struct Box<T>:\n"
                    "    value: T\n"
                    "func main() -> void:\n"
                    "    let a = Box(value: 1)\n"
                    "    let b = Box(value: 2.5)\n")
        names = [n for n in tc.structs if n.startswith('Box__g')]
        self.assertEqual(len(names), 2)

    def test_generic_struct_requires_arguments(self):
        with self.assertRaisesRegex(
                CheckError, r"generic type 'Box' requires type arguments"):
            run("struct Box<T>:\n"
                "    value: T\n"
                "func main() -> void:\n"
                "    let b: Box = Box(value: 1)\n")

    def test_generic_struct_missing_field_raises(self):
        with self.assertRaisesRegex(CheckError, 'missing fields: right'):
            run("struct Pair<T, U>:\n"
                "    left: T\n"
                "    right: U\n"
                "func main() -> void:\n"
                "    let p: Pair<i32, i32> = Pair(left: 1)\n")

    def test_generic_struct_reserved_type_parameter(self):
        with self.assertRaisesRegex(
                CheckError, "type parameter name 'i32' is reserved"):
            run("struct Bad<i32>:\n"
                "    x: i32\n"
                "func main() -> void:\n"
                "    print_i32(1)\n")


    def test_generic_func_infers_from_argument(self):
        _, tc = run("func identity<T>(x: T) -> T:\n"
                    "    return x\n"
                    "func main() -> void:\n"
                    "    let a = identity(5)\n")
        names = [n for n in tc.functions if n.startswith('identity__g')]
        self.assertEqual(len(names), 1)

    def test_generic_func_requires_all_type_params(self):
        with self.assertRaisesRegex(CheckError, 'expects 2 type'):
            run("func mk<T, U>(a: T) -> T:\n"
                "    return a\n"
                "func main() -> void:\n"
                "    let a = mk::<i32>(1)\n")

    def test_generic_func_reserved_type_parameter(self):
        with self.assertRaisesRegex(
                CheckError, "type parameter name 'List' is reserved"):
            run("func bad<List>(x: List) -> List:\n"
                "    return x\n"
                "func main() -> void:\n"
                "    print_i32(1)\n")

if __name__ == '__main__':
    unittest.main()