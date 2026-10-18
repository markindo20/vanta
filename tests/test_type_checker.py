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


if __name__ == '__main__':
    unittest.main()