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

    def test_function_equality_rejected(self):
        with self.assertRaisesRegex(CheckError, "function values cannot be compared"):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "func f() -> void:\n"
                "    let a = sq\n"
                "    let b = sq\n"
                "    print_bool(a == b)\n")

    def test_const_function_rejected(self):
        with self.assertRaisesRegex(CheckError, "constant cannot hold a function value"):
            run("func sq(x: i32) -> i32:\n    return x\n"
                "const G = sq\n"
                "func f() -> void:\n    print_i32(G(1))\n")

    def test_extern_function_type_rejected(self):
        with self.assertRaisesRegex(CheckError,
                                    "extern function 'go' cannot use function types"):
            run('extern "c" {\n    func go(cb: func(i32) -> i32)\n}\n'
                'func f() -> void:\n    return\n')
        with self.assertRaisesRegex(CheckError,
                                    "extern function 'get' cannot use function types"):
            run('extern "c" {\n    func get() -> func(i32) -> i32\n}\n'
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

    def test_at_rejected_on_pointer(self):
        with self.assertRaisesRegex(CheckError, "a pointer has no length"):
            run("func f() -> void:\n"
                "    let a = Arena(64)\n"
                "    let p = a.alloc::<i32>(4)\n"
                "    print_i32(p.at(0))\n")

    def test_at_rejected_on_non_array(self):
        with self.assertRaisesRegex(CheckError, "'at' requires a fixed-size array"):
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


if __name__ == '__main__':
    unittest.main()