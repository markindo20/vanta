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

    def test_match_chain_codegen(self):
        cpp = gen("enum State:\n"
                  "    A\n"
                  "    B\n"
                  "func f(s: State) -> i32:\n"
                  "    match s:\n"
                  "        State.A:\n"
                  "            return 1\n"
                  "        State.B:\n"
                  "            return 2\n")
        self.assertIn('const auto __match_1 = v_s;', cpp)
        self.assertIn('if (__match_1 == State::A) {', cpp)
        self.assertIn('} else if (__match_1 == State::B) {', cpp)

    def test_match_multi_pattern_codegen(self):
        cpp = gen("enum State:\n"
                  "    A\n"
                  "    B\n"
                  "    C\n"
                  "func f(s: State) -> void:\n"
                  "    match s:\n"
                  "        State.A, State.B:\n"
                  "            print_str(\"x\")\n"
                  "        State.C:\n"
                  "            print_str(\"y\")\n")
        self.assertIn('if ((__match_1 == State::A || __match_1 == State::B)) {', cpp)

    def test_match_else_codegen(self):
        cpp = gen("enum State:\n"
                  "    A\n"
                  "    B\n"
                  "func f(s: State) -> void:\n"
                  "    match s:\n"
                  "        State.A:\n"
                  "            print_str(\"x\")\n"
                  "        else:\n"
                  "            print_str(\"y\")\n")
        self.assertIn('} else {', cpp)

    def test_match_value_bound_once(self):
        cpp = gen("enum State:\n"
                  "    A\n"
                  "    B\n"
                  "func pick() -> State:\n"
                  "    return State.A\n"
                  "func f() -> void:\n"
                  "    match pick():\n"
                  "        State.A:\n"
                  "            print_str(\"x\")\n"
                  "        else:\n"
                  "            print_str(\"y\")\n")
        self.assertEqual(cpp.count('const auto __match_1 ='), 1)

    def test_two_matches_get_distinct_temps(self):
        cpp = gen("enum A:\n"
                  "    X\n"
                  "    Y\n"
                  "enum B:\n"
                  "    M\n"
                  "    N\n"
                  "func f(a: A, b: B) -> void:\n"
                  "    match a:\n"
                  "        A.X:\n"
                  "            print_str(\"x\")\n"
                  "        A.Y:\n"
                  "            print_str(\"y\")\n"
                  "    match b:\n"
                  "        B.M:\n"
                  "            print_str(\"m\")\n"
                  "        B.N:\n"
                  "            print_str(\"n\")\n")
        self.assertIn('const auto __match_1 = v_a;', cpp)
        self.assertIn('const auto __match_2 = v_b;', cpp)

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

    def test_extern_callback_param_declarator(self):
        cpp = gen('extern "c" {\n'
                  '    func on(f: func(i32) -> i32, x: i32) -> i32\n'
                  '    func run(cb: func())\n'
                  '}\n'
                  'func sq(x: i32) -> i32:\n    return x * x\n'
                  'func main() -> void:\n    print_i32(on(sq, 2))\n')
        self.assertIn('int32_t on(int32_t(*v_f)(int32_t), int32_t v_x);', cpp)
        self.assertIn('void run(void(*v_cb)());', cpp)
        self.assertIn('on(fn_sq, 2)', cpp)

    def test_extern_ptr_to_callback_param(self):
        cpp = gen('extern "c" {\n'
                  '    func set_slot(slot: ptr<func(i32) -> i32>) -> void\n'
                  '}\n'
                  'func f() -> void:\n'
                  '    return\n')
        self.assertIn('void set_slot(int32_t(**v_slot)(int32_t));', cpp)

    def test_extern_struct_param_qualified(self):
        cpp = gen("struct Point:\n    x: i32\n"
                  "extern \"c\" {\n    func sum(p: ptr<Point>) -> i32\n}\n"
                  "func main() -> void:\n    print_i32(1)\n")
        self.assertIn('namespace vanta_user {\n    struct Point;\n}', cpp)
        self.assertIn('int32_t sum(vanta_user::Point* v_p);', cpp)
        self.assertLess(cpp.index('namespace vanta_user {\n    struct Point;'),
                        cpp.index('extern "C" {'))

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

    def test_extern_function_return_emit(self):
        cpp = gen('extern "c" {\n    func get() -> func(i32) -> i32\n}\n'
                  'func main() -> void:\n'
                  '    let g = get()\n'
                  '    print_i32(g(1))\n')
        self.assertIn('int32_t(*get())(int32_t);', cpp)
        self.assertIn('FnPtr0 v_g = get();', cpp)
        self.assertIn('vanta::print_i32(v_g(1))', cpp)

    def test_extern_ptr_function_return_emit(self):
        cpp = gen('extern "c" {\n    func get() -> ptr<func(i32) -> i32>\n}\n'
                  'func main() -> void:\n    return\n')
        self.assertIn('int32_t(**get())(int32_t);', cpp)

    def test_extern_nested_function_return_emit(self):
        cpp = gen('extern "c" {\n'
                  '    func get() -> func() -> func() -> i32\n'
                  '}\n'
                  'func main() -> void:\n    return\n')
        self.assertIn('int32_t(*(*get())())();', cpp)

    def test_function_equality_emit(self):
        cpp = gen("func sq(x: i32) -> i32:\n    return x\n"
                  "func main() -> void:\n"
                  "    let a = sq\n"
                  "    let b = sq\n"
                  "    print_bool(a == b)\n"
                  "    print_bool(a != b)\n"
                  "    print_bool(ptr_is_null(a))\n")
        self.assertIn('vanta::print_bool((v_a == v_b));', cpp)
        self.assertIn('vanta::print_bool((v_a != v_b));', cpp)
        self.assertIn('vanta::print_bool(((v_a) == nullptr));', cpp)

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

    def test_trig_builtins_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    print_f32(sin_f32(0.5))\n"
                  "    print_f32(cos_f32(0.5))\n"
                  "    print_f32(tan_f32(0.5))\n"
                  "    print_f32(atan2_f32(1.0, 2.0))\n"
                  "    print_f64(sin_f64(0.5))\n")
        self.assertIn('vanta::print_f32(vanta::sin_f32(0.5f))', cpp)
        self.assertIn('vanta::print_f32(vanta::cos_f32(0.5f))', cpp)
        self.assertIn('vanta::print_f32(vanta::tan_f32(0.5f))', cpp)
        self.assertIn('vanta::print_f32(vanta::atan2_f32(1.0f, 2.0f))', cpp)
        self.assertIn('vanta::print_f64(vanta::sin_f64(0.5))', cpp)

    def test_trig_builtin_function_value_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let g: func(f32) -> f32 = sin_f32\n"
                  "    print_f32(g(0.0))\n")
        self.assertIn('using FnPtr0 = float(*)(float);', cpp)
        self.assertIn('FnPtr0 v_g = vanta::sin_f32;', cpp)

    def test_list_create_push_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let xs = a.list::<i32>()\n"
                  "    xs.push(7)\n")
        self.assertIn('vanta::List<int32_t> v_xs = vanta::list_new<int32_t>(v_a);', cpp)
        self.assertIn('vanta::list_push<int32_t>(v_xs, 7);', cpp)

    def test_list_len_and_pop_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let xs = a.list::<i32>()\n"
                  "    print_i32(len(xs))\n"
                  "    print_i32(xs.pop())\n")
        self.assertIn('vanta::print_i32(int32_t((v_xs).h->len));', cpp)
        self.assertIn('vanta::print_i32(vanta::list_pop(v_xs, 5));', cpp)

    def test_list_at_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let xs = a.list::<i32>()\n"
                  "    print_i32(xs.at(1))\n"
                  "    xs.at(1) = 5\n")
        self.assertIn('vanta::print_i32(vanta::list_at_checked(v_xs, 1, 4));', cpp)
        self.assertIn('vanta::list_at_checked_ref(v_xs, 1, 5) = 5;', cpp)

    def test_list_index_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let xs = a.list::<i32>()\n"
                  "    print_i32(xs[0])\n"
                  "    xs[1] = 9\n")
        self.assertIn('vanta::print_i32(v_xs.h->data[0]);', cpp)
        self.assertIn('v_xs.h->data[1] = 9;', cpp)

    def test_list_of_struct_emit(self):
        cpp = gen("struct P:\n    x: i32\n"
                  "func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let ps = a.list::<P>()\n"
                  "    ps.push(P(x: 1))\n")
        self.assertIn('vanta::List<P> v_ps = vanta::list_new<P>(v_a);', cpp)
        self.assertIn('vanta::list_push<P>(v_ps, P{1});', cpp)

    def test_list_param_emit(self):
        cpp = gen("func fill(xs: List<i32>):\n    xs.push(1)\n"
                  "func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let xs = a.list::<i32>()\n"
                  "    fill(xs)\n")
        self.assertIn('void fn_fill(vanta::List<int32_t> v_xs)', cpp)
        self.assertIn('fn_fill(v_xs);', cpp)

    def test_strbuilder_create_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let b = a.str_builder()\n")
        self.assertIn('vanta::StrBuilder v_b = vanta::strb_new(v_a);', cpp)

    def test_strbuilder_append_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let b = a.str_builder()\n"
                  "    b.append_str(\"x=\")\n"
                  "    b.append_i32(41)\n"
                  "    b.append_bool(false)\n")
        self.assertIn('vanta::strb_append_str(v_b, "x=");', cpp)
        self.assertIn('vanta::strb_append_i32(v_b, 41);', cpp)
        self.assertIn('vanta::strb_append_bool(v_b, false);', cpp)

    def test_strbuilder_to_str_and_clear_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let b = a.str_builder()\n"
                  "    print_str(b.to_str())\n"
                  "    b.clear()\n")
        self.assertIn('vanta::print_str(vanta::strb_to_str(v_b));', cpp)
        self.assertIn('vanta::strb_clear(v_b);', cpp)

    def test_strbuilder_len_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let b = a.str_builder()\n"
                  "    print_i32(len(b))\n")
        self.assertIn('vanta::print_i32(int32_t((v_b).h->len));', cpp)

    def test_strbuilder_param_emit(self):
        cpp = gen("func note(b: StrBuilder):\n    b.append_str(\"n\")\n"
                  "func main() -> void:\n"
                  "    let a = Arena(1024)\n"
                  "    let b = a.str_builder()\n"
                  "    note(b)\n")
        self.assertIn('void fn_note(vanta::StrBuilder v_b)', cpp)
        self.assertIn('fn_note(v_b);', cpp)

    def test_enum_decl_emit(self):
        cpp = gen("enum State:\n"
                  "    Menu\n"
                  "    Playing\n"
                  "    Paused\n"
                  "func main() -> void:\n"
                  "    print_str(\"x\")\n")
        self.assertIn('enum class State : int32_t { Menu = 0, Playing = 1, Paused = 2 };', cpp)

    def test_enum_member_ref_emit(self):
        cpp = gen("enum State:\n"
                  "    Menu\n"
                  "    Playing\n"
                  "func main() -> void:\n"
                  "    let s = State.Menu\n"
                  "    if s == State.Playing:\n"
                  "        print_str(\"p\")\n")
        self.assertIn('State v_s = State::Menu;', cpp)
        self.assertIn('(v_s == State::Playing)', cpp)

    def test_enum_to_i32_emit(self):
        cpp = gen("enum State:\n"
                  "    Menu\n"
                  "func main() -> void:\n"
                  "    let s = State.Menu\n"
                  "    print_i32(enum_to_i32(s))\n")
        self.assertIn('vanta::print_i32(static_cast<int32_t>(v_s));', cpp)

    def test_enum_struct_field_emit(self):
        cpp = gen("enum State:\n"
                  "    Menu\n"
                  "struct Game:\n"
                  "    state: State\n"
                  "func main() -> void:\n"
                  "    let g = Game(state: State.Menu)\n"
                  "    print_i32(enum_to_i32(g.state))\n")
        self.assertIn('State v_state;', cpp)
        self.assertIn('Game{State::Menu}', cpp)

    def test_enum_fnptr_alias_emit(self):
        cpp = gen("enum Mode:\n"
                  "    On\n"
                  "func is_on(m: Mode) -> bool:\n"
                  "    return m == Mode.On\n"
                  "func apply(f: func(Mode) -> bool, m: Mode) -> bool:\n"
                  "    return f(m)\n"
                  "func main() -> void:\n"
                  "    print_bool(apply(is_on, Mode.On))\n")
        self.assertIn('using FnPtr0 = bool(*)(Mode);', cpp)

    def test_str_returning_function_default_emit(self):
        cpp = gen("func name(x: i32) -> str:\n"
                  "    if x > 0:\n"
                  "        return \"pos\"\n"
                  "func main() -> void:\n"
                  "    print_str(name(1))\n")
        self.assertIn('return "";', cpp)
        self.assertNotIn('return const char*{};', cpp)

    def test_extern_ptr_void_emit(self):
        cpp = gen("extern \"sdl2\" {\n"
                  "    func SDL_CreateWindow(title: str, flags: u32) -> ptr<void>\n"
                  "    func SDL_DestroyWindow(window: ptr<void>) -> void\n"
                  "}\n"
                  "func main() -> void:\n"
                  "    let w = SDL_CreateWindow(\"x\", 4)\n"
                  "    SDL_DestroyWindow(w)\n")
        self.assertIn('void* SDL_CreateWindow(const char* v_title, uint32_t v_flags);', cpp)
        self.assertIn('void SDL_DestroyWindow(void* v_window);', cpp)

    def test_ptr_void_widening_emit(self):
        cpp = gen("func take(p: ptr<void>) -> void:\n"
                  "    print_str(\"x\")\n"
                  "func main() -> void:\n"
                  "    let a = Arena(256)\n"
                  "    let xs = a.alloc::<i32>(1)\n"
                  "    take(xs)\n")
        self.assertIn('void fn_take(void* v_p)', cpp)
        self.assertIn('fn_take(v_xs);', cpp)

    def test_ptr_is_null_emit(self):
        cpp = gen("func main() -> void:\n"
                  "    let a = Arena(256)\n"
                  "    let xs = a.alloc::<i32>(1)\n"
                  "    print_bool(ptr_is_null(xs))\n")
        self.assertIn('vanta::print_bool(((v_xs) == nullptr));', cpp)

    def test_ptr_returning_function_default_emit(self):
        cpp = gen("extern \"c\" {\n"
                  "    func mk() -> ptr<void>\n"
                  "}\n"
                  "func maybe() -> ptr<void>:\n"
                  "    print_str(\"x\")\n"
                  "func main() -> void:\n"
                  "    print_bool(ptr_is_null(maybe()))\n")
        self.assertIn('return nullptr;', cpp)
        self.assertNotIn('void*{}', cpp)

    # ---------- narrow integers (v0.17.0) ----------

    def test_narrow_types_emit(self):
        cpp = gen("struct P:\n"
                  "    a: i8\n"
                  "    b: u8\n"
                  "    c: i16\n"
                  "    d: u16\n"
                  "func f(x: u8) -> u16:\n"
                  "    return 7\n")
        self.assertIn('int8_t v_a;', cpp)
        self.assertIn('uint8_t v_b;', cpp)
        self.assertIn('int16_t v_c;', cpp)
        self.assertIn('uint16_t v_d;', cpp)
        self.assertIn('uint16_t fn_f(uint8_t v_x);', cpp)

    def test_narrow_arithmetic_promotes_in_cpp(self):
        cpp = gen("func f(a: u8, b: u8) -> i32:\n"
                  "    return a * b\n")
        self.assertIn('return (v_a * v_b);', cpp)

    def test_narrow_struct_ctor_cast(self):
        cpp = gen("struct P:\n"
                  "    r: u8\n"
                  "func main() -> void:\n"
                  "    let z: i32 = 300\n"
                  "    let p = P(r: z)\n")
        self.assertIn('P{static_cast<uint8_t>(v_z)}', cpp)

    def test_narrow_array_literal_cast(self):
        cpp = gen("func main() -> void:\n"
                  "    let z: i32 = 7\n"
                  "    let bytes: [u8, 2] = [z, 3]\n")
        self.assertIn('std::array<uint8_t, 2>{static_cast<uint8_t>(v_z), 3}', cpp)

    def test_narrow_fmt_spec(self):
        cpp = gen("func f(a: u8) -> void:\n"
                  "    print_fmt(\"a={}\", a)\n")
        self.assertIn('"a=%d\\n"', cpp)

    def test_narrow_list_push_template_arg(self):
        cpp = gen("func f(x: i32) -> void:\n"
                  "    let a = Arena(256)\n"
                  "    let xs = a.list::<u8>()\n"
                  "    xs.push(x)\n")
        self.assertIn('vanta::list_push<uint8_t>(v_xs, v_x);', cpp)

    # ---------- ptr_cast (v0.17.0) ----------

    def test_ptr_cast_emit(self):
        cpp = gen("func f(p: ptr<void>) -> void:\n"
                  "    let q = ptr_cast::<f32>(p)\n"
                  "    print_f32(q[0])\n")
        self.assertIn('reinterpret_cast<float*>(v_p)', cpp)

    def test_ptr_cast_struct_emit(self):
        cpp = gen("struct P:\n"
                  "    x: i32\n"
                  "func f(p: ptr<void>) -> void:\n"
                  "    let q = ptr_cast::<P>(p)\n"
                  "    print_i32(q[0].x)\n")
        self.assertIn('reinterpret_cast<P*>(v_p)', cpp)

    # ---------- ptr_offset (v0.18.0) ----------

    def test_ptr_offset_emit(self):
        cpp = gen("func f(p: ptr<i32>, n: i32) -> void:\n"
                  "    let q = ptr_offset(p, n)\n"
                  "    q[0] = 1\n")
        self.assertIn('((v_p) + (v_n))', cpp)

    def test_ptr_offset_literal_emit(self):
        cpp = gen("func f(p: ptr<i32>) -> void:\n"
                  "    let q = ptr_offset(p, 2)\n"
                  "    q[0] = 1\n")
        self.assertIn('((v_p) + (2))', cpp)

    # ---------- ptr_null (v0.19.0) ----------

    def test_ptr_null_emit(self):
        cpp = gen("func f() -> void:\n"
                  "    let p = ptr_null::<i32>()\n"
                  "    print_bool(ptr_is_null(p))\n")
        self.assertIn('int32_t* v_p = nullptr;', cpp)

    def test_ptr_null_func_field_emit(self):
        # A func-typed struct field is a C function pointer, and ptr_null
        # fills it with nullptr — the shape SDL_AudioSpec's callback needs.
        cpp = gen("struct S:\n"
                  "    cb: func(i32) -> i32\n"
                  "func f() -> void:\n"
                  "    let s = S(cb: ptr_null::<func(i32) -> i32>())\n")
        self.assertIn('using FnPtr0 = int32_t(*)(int32_t);', cpp)
        self.assertIn('FnPtr0 v_cb;', cpp)
        self.assertIn('S{nullptr}', cpp)

    # ---------- enums in extern (v0.17.0) ----------

    def test_extern_enum_emit(self):
        cpp = gen("enum Mode:\n"
                  "    On\n"
                  "    Off\n"
                  "extern \"demo\" {\n"
                  "    func set_mode(m: Mode) -> Mode\n"
                  "}\n")
        self.assertIn('enum class Mode : int32_t;', cpp)
        self.assertIn('vanta_user::Mode set_mode(vanta_user::Mode v_m);', cpp)
        self.assertIn('enum class Mode : int32_t { On = 0, Off = 1 };', cpp)

    # ---------- struct equality (v0.17.0) ----------

    def test_struct_eq_emit(self):
        cpp = gen("struct Inner:\n"
                  "    q: str\n"
                  "struct P:\n"
                  "    r: u8\n"
                  "    names: [str, 2]\n"
                  "    inner: Inner\n"
                  "func main() -> void:\n"
                  "    print_i32(1)\n")
        self.assertIn('inline bool operator==(const P& a, const P& b);', cpp)
        self.assertIn('inline bool operator!=(const P& a, const P& b);', cpp)
        self.assertIn('return (a.v_r == b.v_r) && '
                      '(vanta::str_eq(a.v_names[0], b.v_names[0]) && '
                      'vanta::str_eq(a.v_names[1], b.v_names[1])) && '
                      '(a.v_inner == b.v_inner);', cpp)
        self.assertIn('inline bool operator!=(const P& a, const P& b) { return !(a == b); }', cpp)

    def test_struct_eq_function_field_emit(self):
        cpp = gen("struct Handler:\n"
                  "    cb: func(i32) -> i32\n"
                  "    n: i32\n"
                  "func main() -> void:\n"
                  "    print_i32(1)\n")
        self.assertIn('return (a.v_cb == b.v_cb) && (a.v_n == b.v_n);', cpp)

    def test_struct_eq_not_emitted_for_uncomparable(self):
        cpp = gen("struct Q:\n"
                  "    p: ptr<i32>\n"
                  "func main() -> void:\n"
                  "    print_i32(1)\n")
        self.assertNotIn('operator==', cpp)

    # ---------- for-each (v0.17.0) ----------

    def test_foreach_list_emit(self):
        cpp = gen("func f(xs: List<i32>) -> void:\n"
                  "    for x in xs:\n"
                  "        print_i32(x)\n")
        self.assertIn('vanta::List<int32_t> __it_1 = v_xs;', cpp)
        self.assertIn('for (int32_t __i_1 = 0; __i_1 < __it_1.h->len; __i_1 += 1) {', cpp)
        self.assertIn('int32_t v_x = __it_1.h->data[__i_1];', cpp)

    def test_foreach_array_emit(self):
        cpp = gen("func f() -> void:\n"
                  "    let xs = [1, 2, 3]\n"
                  "    for x in xs:\n"
                  "        print_i32(x)\n")
        self.assertIn('const std::array<int32_t, 3>& __it_1 = v_xs;', cpp)
        self.assertIn('for (int32_t __i_1 = 0; __i_1 < 3; __i_1 += 1) {', cpp)
        self.assertIn('int32_t v_x = __it_1[__i_1];', cpp)


if __name__ == '__main__':
    unittest.main()