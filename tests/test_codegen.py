import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.type_checker import TypeChecker
from compiler.codegen_cpp import CodeGen


def gen(src):
    toks = Lexer(src).tokenize()
    prog = Parser(toks).parse_program()
    tc = TypeChecker(prog)
    tc.register()
    tc.check()
    return CodeGen(prog, tc).generate()


class CodegenTests(unittest.TestCase):
    def test_hello(self):
        cpp = gen("func main() -> void:\n    print_i32(42)\n")
        self.assertIn('vanta::print_i32(42)', cpp)
        self.assertIn('int main(int argc, char** argv)', cpp)

    def test_struct(self):
        cpp = gen("struct P:\n    x: i32\n"
                  "func main() -> void:\n    let p = P(x: 1)\n    print_i32(p.x)\n")
        self.assertIn('struct P {', cpp)
        self.assertIn('v_p.v_x', cpp)

    def test_control_flow(self):
        cpp = gen("func main() -> void:\n    for i in range(0, 3):\n        print_i32(i)\n")
        self.assertIn('for (int32_t v_i = 0;', cpp)
        self.assertIn('v_i = v_i + 1', cpp)

    def test_math(self):
        cpp = gen("func main() -> void:\n    let v = Vec3(1.0, 2.0, 3.0)\n    print_f32(v.x)\n")
        self.assertIn('vanta::Vec3(1.0f, 2.0f, 3.0f)', cpp)

    def test_compound_assign_codegen(self):
        cpp = gen("func main() -> void:\n    mut x = 1\n    x += 2\n")
        self.assertIn('v_x = (v_x + 2)', cpp)

    def test_compound_assign_member(self):
        cpp = gen("struct P:\n    x: i32\n"
                  "func main() -> void:\n    mut p = P(x: 0)\n    p.x += 5\n")
        self.assertIn('v_p.v_x = (v_p.v_x + 5)', cpp)

    def test_break_continue_codegen(self):
        cpp = gen("func main() -> void:\n"
                  "    for i in range(0, 5):\n"
                  "        if i == 2:\n"
                  "            break\n"
                  "        if i == 1:\n"
                  "            continue\n")
        self.assertIn('break;', cpp)
        self.assertIn('continue;', cpp)

    def test_const_emitted(self):
        cpp = gen("const X: i32 = 5\nfunc main() -> void:\n    print_i32(X)\n")
        self.assertIn('constexpr int32_t v_X = 5', cpp)
        self.assertIn('print_i32(v_X)', cpp)

    def test_assert_emitted(self):
        cpp = gen("func main() -> void:\n    assert(1 == 1)\n")
        self.assertIn('vanta::assert_impl(', cpp)

    def test_range_3arg_codegen(self):
        cpp = gen("func main() -> void:\n    for i in range(10, 0, -1):\n        print_i32(i)\n")
        self.assertIn('__step_1', cpp)
        self.assertIn('__end_1', cpp)

    def test_inferred_return_codegen(self):
        cpp = gen("func add(a: i32, b: i32):\n    return a + b\n"
                  "func main() -> void:\n    print_i32(add(1, 2))\n")
        self.assertIn('int32_t fn_add(', cpp)

    def test_array_emit(self):
        cpp = gen("func main() -> void:\n    let xs = [1, 2, 3]\n    print_i32(xs[0])\n")
        self.assertIn('std::array<int32_t, 3>{1, 2, 3}', cpp)
        self.assertIn('v_xs[0]', cpp)

    def test_len_emit(self):
        cpp = gen("func main() -> void:\n    let xs = [1, 2, 3]\n    let n = len(xs)\n")
        self.assertIn('.size()', cpp)

    def test_arena_rows_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let arena = Arena(1024)\n"
                  "    let rows = arena.alloc::<[i32, 4]>(2)\n"
                  "    rows[0][1] = 5\n")
        self.assertIn('.alloc<std::array<int32_t, 4>>(2)', cpp)
        self.assertIn('v_rows[0][1] = 5;', cpp)

    def test_struct_grid_field_write_emit(self):
        cpp = gen("struct B:\n    cells: [[i32, 2], 2]\n"
                  "func main() -> void:\n"
                  "    mut b = B(cells: [[1, 2], [3, 4]])\n"
                  "    b.cells[1][0] = 5\n")
        self.assertIn('v_b.v_cells[1][0] = 5;', cpp)

    def test_quat_mul_emit(self):
        cpp = gen("func main() -> void:\n    let q = Quat(0.0, 0.0, 0.0, 1.0)\n    let r = q * q\n")
        self.assertIn('(v_q * v_q)', cpp)

    def test_string_lit_emit(self):
        cpp = gen('func main() -> void:\n    print_str("hi")\n')
        self.assertIn('vanta::print_str("hi")', cpp)

    def test_string_escape_emit(self):
        cpp = gen(r'func main() -> void:' + '\n' + r'    print_str("a\nb")' + '\n')
        self.assertIn('\\n', cpp)

    def test_str_eq_emit(self):
        cpp = gen('func main() -> void:\n    let b = "a" == "b"\n')
        self.assertIn('vanta::str_eq', cpp)

    def test_translation_emit(self):
        cpp = gen("func main() -> void:\n    let m = translation(1.0, 2.0, 3.0)\n")
        self.assertIn('vanta::mat4_translation(', cpp)

    def test_vec2_normalized_emit(self):
        cpp = gen("func main() -> void:\n    let v = Vec2(3.0, 4.0)\n    let n = v.normalized()\n")
        self.assertIn('vanta::normalize(v_v)', cpp)


    def test_rand_emit(self):
        cpp = gen("func main() -> void:\n    let r = rand_f32()\n    rand_seed(7)\n")
        self.assertIn('vanta::rand_f32()', cpp)
        self.assertIn('vanta::rand_seed(7)', cpp)


    def test_write_and_math_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    write_str(\"x\")\n"
                  "    print_newline()\n"
                  "    let a = min_i32(1, 2)\n"
                  "    let b = floor_f32(1.5)\n")
        self.assertIn('vanta::write_str("x")', cpp)
        self.assertIn('vanta::print_newline()', cpp)
        self.assertIn('vanta::min_i32(1, 2)', cpp)
        self.assertIn('vanta::floor_f32(1.5f)', cpp)


    def test_main_receives_args(self):
        cpp = gen("func main() -> void:\n    print_i32(arg_count())\n")
        self.assertIn('int main(int argc, char** argv)', cpp)
        self.assertIn('vanta::set_args(argc, argv);', cpp)
        self.assertIn('vanta::arg_count()', cpp)


    def test_print_fmt_emit(self):
        cpp = gen('func main() -> void:\n    print_fmt("n={} f={} b={}", 3, 1.5, true)\n')
        self.assertIn('vanta::print_fmt_impl("n=%d f=%f b=%s\\n", 3, 1.5f, '
                      '(true ? "true" : "false"))', cpp)

    def test_write_fmt_has_no_newline(self):
        cpp = gen('func main() -> void:\n    write_fmt("x{}", 1)\n')
        self.assertIn('vanta::print_fmt_impl("x%d", 1)', cpp)

    def test_fmt_escapes_percent(self):
        cpp = gen('func main() -> void:\n    print_fmt("100% sure")\n')
        self.assertIn('"100%% sure\\n"', cpp)

    def test_str_concat_emit(self):
        cpp = gen('func main() -> void:\n    let s = str_concat("a", "b")\n')
        self.assertIn('vanta::str_concat("a", "b")', cpp)


    def test_str_to_number_emit(self):
        cpp = gen('func main() -> void:\n    let a = str_to_i32("12")\n')
        self.assertIn('vanta::str_to_i32("12")', cpp)

    def test_file_io_emit(self):
        cpp = gen('func main() -> void:\n'
                  '    let e = file_exists("a")\n'
                  '    let w = file_write("a", "b")\n'
                  '    let r = file_read("a")\n')
        self.assertIn('vanta::file_exists("a")', cpp)
        self.assertIn('vanta::file_write("a", "b")', cpp)
        self.assertIn('vanta::file_read("a")', cpp)

    def test_extern_block_emitted_outside_namespace(self):
        cpp = gen('extern "mylib" {\n    func add(a: i32, b: i32) -> i32\n}\n'
                  'func main() -> void:\n    print_i32(add(1, 2))\n')
        self.assertIn('extern "C" {', cpp)
        self.assertIn('int32_t add(int32_t v_a, int32_t v_b);', cpp)
        self.assertLess(cpp.index('extern "C"'), cpp.index('namespace vanta_user'))

    def test_extern_call_has_no_prefix(self):
        cpp = gen('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
                  'func main() -> void:\n    print_i32(add(1, 2))\n')
        self.assertIn('vanta::print_i32(add(1, 2))', cpp)
        self.assertNotIn('fn_add', cpp)

    def test_extern_void_return_defaults(self):
        cpp = gen('extern "c" {\n    func log(msg: str)\n}\n'
                  'func main() -> void:\n    log("hi")\n')
        self.assertIn('void log(const char* v_msg);', cpp)
        self.assertIn('log("hi")', cpp)

    def test_user_function_still_prefixed(self):
        cpp = gen('func add(a: i32, b: i32) -> i32:\n    return a + b\n'
                  'func main() -> void:\n    print_i32(add(1, 2))\n')
        self.assertIn('int32_t fn_add(int32_t v_a, int32_t v_b);', cpp)
        self.assertIn('vanta::print_i32(fn_add(1, 2))', cpp)

    def test_function_pointer_alias_emitted(self):
        cpp = gen("func sq(x: i32) -> i32:\n    return x\n"
                  "func main() -> void:\n    let g = sq\n")
        self.assertIn('using FnPtr0 = int32_t(*)(int32_t);', cpp)
        self.assertLess(cpp.index('using FnPtr0'), cpp.index('fn_sq'))

    def test_function_value_reference_prefixed(self):
        cpp = gen("func sq(x: i32) -> i32:\n    return x\n"
                  "func main() -> void:\n    let g: func(i32) -> i32 = sq\n")
        self.assertIn('FnPtr0 v_g = fn_sq;', cpp)

    def test_builtin_function_value(self):
        cpp = gen("func main() -> void:\n    let logger: func(str) = print_str\n")
        self.assertIn('using FnPtr0 = void(*)(const char*);', cpp)
        self.assertIn('FnPtr0 v_logger = vanta::print_str;', cpp)

    def test_indirect_call_emit(self):
        cpp = gen("func sq(x: i32) -> i32:\n    return x\n"
                  "func main() -> void:\n"
                  "    let g: func(i32) -> i32 = sq\n"
                  "    print_i32(g(3))\n")
        self.assertIn('vanta::print_i32(v_g(3))', cpp)

    def test_struct_field_function_type(self):
        cpp = gen("func sq(x: i32) -> i32:\n    return x\n"
                  "struct H:\n    cb: func(i32) -> i32\n"
                  "func main() -> void:\n"
                  "    let h = H(cb: sq)\n"
                  "    print_i32(h.cb(2))\n")
        self.assertIn('FnPtr0 v_cb;', cpp)
        self.assertIn('vanta::print_i32(v_h.v_cb(2))', cpp)

    def test_array_of_function_pointers(self):
        cpp = gen("func inc(x: i32) -> i32:\n    return x + 1\n"
                  "func dec(x: i32) -> i32:\n    return x - 1\n"
                  "func main() -> void:\n"
                  "    let fs: [func(i32) -> i32, 2] = [inc, dec]\n"
                  "    print_i32(fs[1](4))\n")
        self.assertIn('std::array<FnPtr0, 2>{fn_inc, fn_dec}', cpp)
        self.assertIn('vanta::print_i32(v_fs[1](4))', cpp)

    def test_function_return_type(self):
        cpp = gen("func inc(x: i32) -> i32:\n    return x + 1\n"
                  "func pick() -> func(i32) -> i32:\n    return inc\n"
                  "func main() -> void:\n    let g = pick()\n")
        self.assertIn('FnPtr0 fn_pick();', cpp)
        self.assertIn('return fn_inc;', cpp)

    def test_nested_function_type_alias_order(self):
        cpp = gen("func inc(x: i32) -> i32:\n    return x + 1\n"
                  "func twice(f: func(i32) -> i32, x: i32) -> i32:\n"
                  "    return f(f(x))\n"
                  "func main() -> void:\n"
                  "    let t: func(func(i32) -> i32, i32) -> i32 = twice\n")
        self.assertIn('using FnPtr1 = int32_t(*)(FnPtr0, int32_t);', cpp)
        self.assertLess(cpp.index('using FnPtr0'), cpp.index('using FnPtr1'))

    def test_extern_function_value_unprefixed(self):
        cpp = gen('extern "c" {\n    func add(a: i32, b: i32) -> i32\n}\n'
                  'func main() -> void:\n'
                  '    let op: func(i32, i32) -> i32 = add\n'
                  '    print_i32(op(1, 2))\n')
        self.assertIn('FnPtr0 v_op = add;', cpp)
        self.assertIn('vanta::print_i32(v_op(1, 2))', cpp)
        self.assertNotIn('fn_add', cpp)

    def test_alloc_of_function_pointer(self):
        cpp = gen("func inc(x: i32) -> i32:\n    return x + 1\n"
                  "func main() -> void:\n"
                  "    let a = Arena(64)\n"
                  "    let s = a.alloc::<func(i32) -> i32>(2)\n"
                  "    s[0] = inc\n"
                  "    print_i32(s[0](1))\n")
        self.assertIn('FnPtr0* v_s = v_a.alloc<FnPtr0>(2);', cpp)
        self.assertIn('vanta::print_i32(v_s[0](1))', cpp)

    def test_at_read_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let xs: [i32, 3] = [1, 2, 3]\n"
                  "    print_i32(xs.at(1))\n")
        self.assertIn('vanta::print_i32(vanta::at_checked(v_xs, 1, 3))', cpp)

    def test_at_write_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    mut xs: [i32, 3] = [1, 2, 3]\n"
                  "    xs.at(0) = 9\n")
        self.assertIn('vanta::at_checked_ref(v_xs, 0, 3) = 9;', cpp)

    def test_at_nested_chain_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    mut g: [[i32, 2], 2] = [[1, 2], [3, 4]]\n"
                  "    g.at(0).at(1) = 7\n"
                  "    print_i32(g.at(1).at(0))\n")
        self.assertIn('vanta::at_checked_ref(vanta::at_checked_ref(v_g, 0, 3), 1, 3) = 7;', cpp)
        self.assertIn('vanta::print_i32(vanta::at_checked(vanta::at_checked(v_g, 1, 4), 0, 4))', cpp)

    def test_at_compound_write_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    mut xs: [i32, 3] = [1, 2, 3]\n"
                  "    xs.at(1) += 2\n")
        self.assertIn('vanta::at_checked_ref(v_xs, 1, 3) = (vanta::at_checked(v_xs, 1, 3) + 2);', cpp)


if __name__ == '__main__':
    unittest.main()