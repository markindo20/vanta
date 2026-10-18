#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstddef>
#include <cstdarg>
#include <array>

namespace vanta {

// ---------- Vec2 ----------
struct Vec2 {
    float x, y;
    Vec2() : x(0), y(0) {}
    Vec2(float x_, float y_) : x(x_), y(y_) {}
};
inline Vec2 operator+(Vec2 a, Vec2 b) { return Vec2(a.x + b.x, a.y + b.y); }
inline Vec2 operator-(Vec2 a, Vec2 b) { return Vec2(a.x - b.x, a.y - b.y); }
inline Vec2 operator*(Vec2 a, Vec2 b) { return Vec2(a.x * b.x, a.y * b.y); }
inline Vec2 operator*(Vec2 a, float s) { return Vec2(a.x * s, a.y * s); }
inline Vec2 operator*(float s, Vec2 a) { return a * s; }
inline Vec2 operator/(Vec2 a, float s) { return Vec2(a.x / s, a.y / s); }
inline bool operator==(Vec2 a, Vec2 b) { return a.x == b.x && a.y == b.y; }
inline bool operator!=(Vec2 a, Vec2 b) { return !(a == b); }
inline float dot(Vec2 a, Vec2 b) { return a.x * b.x + a.y * b.y; }
inline float length(Vec2 a) { return std::sqrt(dot(a, a)); }
inline Vec2 normalize(Vec2 a) {
    float l = length(a);
    return l > 0.0f ? a / l : Vec2(0, 0);
}

// ---------- Vec3 ----------
struct Vec3 {
    float x, y, z;
    Vec3() : x(0), y(0), z(0) {}
    Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
};
inline Vec3 operator+(Vec3 a, Vec3 b) { return Vec3(a.x + b.x, a.y + b.y, a.z + b.z); }
inline Vec3 operator-(Vec3 a, Vec3 b) { return Vec3(a.x - b.x, a.y - b.y, a.z - b.z); }
inline Vec3 operator*(Vec3 a, Vec3 b) { return Vec3(a.x * b.x, a.y * b.y, a.z * b.z); }
inline Vec3 operator*(Vec3 a, float s) { return Vec3(a.x * s, a.y * s, a.z * s); }
inline Vec3 operator*(float s, Vec3 a) { return a * s; }
inline Vec3 operator/(Vec3 a, float s) { return Vec3(a.x / s, a.y / s, a.z / s); }
inline bool operator==(Vec3 a, Vec3 b) { return a.x == b.x && a.y == b.y && a.z == b.z; }
inline bool operator!=(Vec3 a, Vec3 b) { return !(a == b); }
inline float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 cross(Vec3 a, Vec3 b) {
    return Vec3(a.y * b.z - a.z * b.y,
                a.z * b.x - a.x * b.z,
                a.x * b.y - a.y * b.x);
}
inline float length(Vec3 a) { return std::sqrt(dot(a, a)); }
inline Vec3 normalize(Vec3 a) {
    float l = length(a);
    return l > 0.0f ? a / l : Vec3(0, 0, 0);
}

// ---------- Quat ----------
struct Quat {
    float x, y, z, w;
    Quat() : x(0), y(0), z(0), w(1) {}
    Quat(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}
};

inline Quat operator*(Quat a, Quat b) {
    return Quat(
        a.w*b.x + a.x*b.w + a.y*b.z - a.z*b.y,
        a.w*b.y - a.x*b.z + a.y*b.w + a.z*b.x,
        a.w*b.z + a.x*b.y - a.y*b.x + a.z*b.w,
        a.w*b.w - a.x*b.x - a.y*b.y - a.z*b.z
    );
}

inline Vec3 operator*(Quat q, Vec3 v) {
    Vec3 u(q.x, q.y, q.z);
    float s = q.w;
    Vec3 uv = cross(u, v);
    Vec3 uuv = cross(u, uv);
    return v + 2.0f * (s * uv + uuv);
}

inline Vec3 operator*(Vec3 v, Quat q) {
    return Quat(-q.x, -q.y, -q.z, q.w) * v;
}

inline float dot(Quat a, Quat b) {
    return a.x*b.x + a.y*b.y + a.z*b.z + a.w*b.w;
}
inline float length(Quat q) {
    return std::sqrt(dot(q, q));
}
inline Quat normalize(Quat q) {
    float l = length(q);
    return l > 0.0f ? Quat(q.x/l, q.y/l, q.z/l, q.w/l) : Quat(0, 0, 0, 1);
}

// ---------- Matrix4 (row-major) ----------
struct Matrix4 {
    float m[16];
    Matrix4() {
        for (int i = 0; i < 16; ++i) m[i] = 0.0f;
        m[0] = m[5] = m[10] = m[15] = 1.0f;
    }
};

inline Vec3 operator*(const Matrix4& M, Vec3 v) {
    return Vec3(
        M.m[0] * v.x + M.m[1] * v.y + M.m[2] * v.z + M.m[3],
        M.m[4] * v.x + M.m[5] * v.y + M.m[6] * v.z + M.m[7],
        M.m[8] * v.x + M.m[9] * v.y + M.m[10] * v.z + M.m[11]
    );
}

inline Matrix4 operator*(const Matrix4& A, const Matrix4& B) {
    Matrix4 R;
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) {
                s += A.m[i*4+k] * B.m[k*4+j];
            }
            R.m[i*4+j] = s;
        }
    }
    return R;
}

inline Matrix4 mat4_translation(float x, float y, float z) {
    Matrix4 M;
    M.m[3] = x;
    M.m[7] = y;
    M.m[11] = z;
    return M;
}

inline Matrix4 mat4_scale(float s) {
    Matrix4 M;
    M.m[0] = M.m[5] = M.m[10] = s;
    return M;
}

inline Matrix4 mat4_from_quat(Quat q) {
    Matrix4 M;
    float xx = q.x*q.x, yy = q.y*q.y, zz = q.z*q.z;
    float xy = q.x*q.y, xz = q.x*q.z, yz = q.y*q.z;
    float wx = q.w*q.x, wy = q.w*q.y, wz = q.w*q.z;
    M.m[0] = 1 - 2*(yy + zz);
    M.m[1] = 2*(xy - wz);
    M.m[2] = 2*(xz + wy);
    M.m[4] = 2*(xy + wz);
    M.m[5] = 1 - 2*(xx + zz);
    M.m[6] = 2*(yz - wx);
    M.m[8] = 2*(xz - wy);
    M.m[9] = 2*(yz + wx);
    M.m[10] = 1 - 2*(xx + yy);
    return M;
}

// ---------- Arena allocator ----------
class Arena {
public:
    Arena(int32_t bytes) : size_((uint32_t)bytes), offset_(0) {
        data_ = static_cast<char*>(std::malloc((size_t)bytes));
        if (!data_) { std::fprintf(stderr, "vanta: arena alloc failed\n"); std::exit(1); }
    }
    ~Arena() { std::free(data_); }
    Arena(const Arena&) = delete;
    Arena& operator=(const Arena&) = delete;
    Arena(Arena&&) = delete;
    Arena& operator=(Arena&&) = delete;

    void* raw_alloc(uint32_t bytes, uint32_t align) {
        uintptr_t base = reinterpret_cast<uintptr_t>(data_) + offset_;
        uintptr_t aligned = (base + (align - 1)) & ~((uintptr_t)align - 1);
        uint32_t new_off = (uint32_t)(aligned - reinterpret_cast<uintptr_t>(data_) + bytes);
        if (new_off > size_) {
            std::fprintf(stderr, "vanta: arena out of memory\n");
            std::exit(1);
        }
        offset_ = new_off;
        return reinterpret_cast<void*>(aligned);
    }

    template <typename T>
    T* alloc(int32_t count) {
        return static_cast<T*>(raw_alloc((uint32_t)(sizeof(T) * (size_t)count), (uint32_t)alignof(T)));
    }

    void reset() { offset_ = 0; }

private:
    char* data_;
    uint32_t size_;
    uint32_t offset_;
};

// ---------- Assertions ----------
inline void assert_impl(bool cond, int32_t line) {
    if (!cond) {
        std::fprintf(stderr, "vanta: assertion failed at line %d\n", (int)line);
        std::exit(1);
    }
}

// ---------- Bounds-checked array access ----------
// xs.at(i) compiles down to these. Unlike xs[i], the index is checked first:
// an out-of-bounds read or write stops the program with the array size and
// the source line of the access. at_checked returns a copy so it also works
// on temporary (prvalue) receivers; at_checked_ref returns the real element
// so writes land in the array.
inline void index_fail(int32_t index, int32_t size, int32_t line) {
    std::fprintf(stderr, "vanta: index %d out of bounds (size %d) at line %d\n",
                 (int)index, (int)size, (int)line);
    std::exit(1);
}

template <typename T, size_t N>
inline T at_checked(const std::array<T, N>& xs, int32_t index, int32_t line) {
    if (index < 0 || (size_t)index >= N) index_fail(index, (int32_t)N, line);
    return xs[(size_t)index];
}

template <typename T, size_t N>
inline T& at_checked_ref(std::array<T, N>& xs, int32_t index, int32_t line) {
    if (index < 0 || (size_t)index >= N) index_fail(index, (int32_t)N, line);
    return xs[(size_t)index];
}

// ---------- Built-in IO / math ----------
inline void print_i32(int32_t v) { std::printf("%d\n", (int)v); }
inline void print_u32(uint32_t v) { std::printf("%u\n", (unsigned)v); }
inline void print_f32(float v) { std::printf("%f\n", (double)v); }
inline void print_f64(double v) { std::printf("%lf\n", v); }
inline void print_bool(bool v) { std::printf("%s\n", v ? "true" : "false"); }
inline void print_str(const char* s) { std::printf("%s\n", s); }
inline void print_newline() { std::printf("\n"); }
inline float sqrt_f32(float v) { return std::sqrt(v); }
inline double sqrt_f64(double v) { return std::sqrt(v); }
inline float i32_to_f32(int32_t v) { return (float)v; }
inline int32_t f32_to_i32(float v) { return (int32_t)v; }

// ---------- Output without a trailing newline ----------
inline void write_i32(int32_t v) { std::printf("%d", (int)v); }
inline void write_u32(uint32_t v) { std::printf("%u", (unsigned)v); }
inline void write_f32(float v) { std::printf("%f", (double)v); }
inline void write_f64(double v) { std::printf("%lf", v); }
inline void write_bool(bool v) { std::printf("%s", v ? "true" : "false"); }
inline void write_str(const char* s) { std::printf("%s", s); }

// ---------- Scalar math ----------
inline int32_t abs_i32(int32_t v) { return v < 0 ? -v : v; }
inline float abs_f32(float v) { return std::fabs(v); }
inline int32_t min_i32(int32_t a, int32_t b) { return a < b ? a : b; }
inline int32_t max_i32(int32_t a, int32_t b) { return a > b ? a : b; }
inline float min_f32(float a, float b) { return a < b ? a : b; }
inline float max_f32(float a, float b) { return a > b ? a : b; }
inline float floor_f32(float v) { return std::floor(v); }
inline float ceil_f32(float v) { return std::ceil(v); }

// ---------- String helpers ----------
inline bool str_eq(const char* a, const char* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return std::strcmp(a, b) == 0;
}
inline int32_t str_len(const char* s) { return (int32_t)std::strlen(s); }
// strtol/strtod parse a leading number and yield 0 when there is none.
inline int32_t str_to_i32(const char* s) {
    return (int32_t)std::strtol(s ? s : "", nullptr, 10);
}
inline float str_to_f32(const char* s) {
    return (float)std::strtod(s ? s : "", nullptr);
}

// ---------- Formatted output ----------
// print_fmt / write_fmt compile down to this. The format string is built at
// compile time, so all argument checking happened before we got here.
inline void print_fmt_impl(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::vprintf(fmt, ap);
    va_end(ap);
}

// ---------- String pool ----------
// str_concat and the to_str_* helpers need somewhere to put their results.
// Vanta's `str` is a plain const char*, and the Arena is user-scoped, so we
// bump-allocate from a fixed process-lifetime pool. It is never freed; call
// str_pool_reset() to reclaim it, and note that strings built from the pool
// are invalidated by a reset.
inline const uint32_t STR_POOL_SIZE = 1u << 16;  // 64 KiB
inline char*& str_pool_base() { static char* p = nullptr; return p; }
inline uint32_t& str_pool_used() { static uint32_t u = 0; return u; }

inline char* str_pool_alloc(uint32_t n) {
    if (str_pool_base() == nullptr) {
        str_pool_base() = (char*)std::malloc(STR_POOL_SIZE);
        if (!str_pool_base()) { std::fprintf(stderr, "vanta: string pool alloc failed\n"); std::exit(1); }
    }
    if (str_pool_used() + n > STR_POOL_SIZE) {
        std::fprintf(stderr, "vanta: string pool exhausted (%u bytes); call str_pool_reset()\n",
                     (unsigned)STR_POOL_SIZE);
        std::exit(1);
    }
    char* r = str_pool_base() + str_pool_used();
    str_pool_used() += n;
    return r;
}
inline void str_pool_reset() { str_pool_used() = 0; }

inline const char* str_concat(const char* a, const char* b) {
    uint32_t la = (uint32_t)std::strlen(a), lb = (uint32_t)std::strlen(b);
    char* r = str_pool_alloc(la + lb + 1);
    std::memcpy(r, a, la);
    std::memcpy(r + la, b, lb);
    r[la + lb] = '\0';
    return r;
}
inline const char* to_str_i32(int32_t v) {
    char* r = str_pool_alloc(12);
    std::snprintf(r, 12, "%d", (int)v);
    return r;
}
inline const char* to_str_f32(float v) {
    char* r = str_pool_alloc(32);
    std::snprintf(r, 32, "%f", (double)v);
    return r;
}
inline const char* to_str_bool(bool v) { return v ? "true" : "false"; }

// ---------- File I/O ----------
// Paths and contents are plain `str` (bare const char*). file_read allocates
// from the string pool above, so it obeys the same rules: the result is valid
// until the next str_pool_reset(). An empty file and a missing file both read
// as "", so use file_exists() when the difference matters. "Text mode" is not
// a thing here: files are read and written as bytes, but Vanta strings are
// NUL-terminated, so file_read() of a file containing NUL bytes is truncated
// at the first NUL when consumed by other string operations.
inline bool file_exists(const char* path) {
    std::FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    std::fclose(f);
    return true;
}
inline int32_t file_write(const char* path, const char* data) {
    std::FILE* f = std::fopen(path, "wb");
    if (!f) return -1;
    size_t n = std::fwrite(data, 1, std::strlen(data), f);
    if (std::fclose(f) != 0) return -1;
    return (int32_t)n;
}
inline const char* file_read(const char* path) {
    std::FILE* f = std::fopen(path, "rb");
    if (!f) return "";
    if (std::fseek(f, 0, SEEK_END) != 0) { std::fclose(f); return ""; }
    long sz = std::ftell(f);
    if (sz < 0 || std::fseek(f, 0, SEEK_SET) != 0) { std::fclose(f); return ""; }
    if ((uint64_t)sz + 1 > STR_POOL_SIZE) {
        std::fprintf(stderr, "vanta: file '%s' (%ld bytes) does not fit the %u-byte string pool\n",
                     path, sz, (unsigned)STR_POOL_SIZE);
        std::exit(1);
    }
    char* r = str_pool_alloc((uint32_t)sz + 1);
    size_t got = std::fread(r, 1, (size_t)sz, f);
    std::fclose(f);
    if (got != (size_t)sz) return "";
    r[got] = '\0';
    return r;
}

// ---------- Pseudo-random (xorshift32) ----------
// Deterministic by default so programs are reproducible across runs.
// Call rand_seed(...) to pick a different stream.
inline uint32_t& rand_state() {
    static uint32_t s = 0x12345678u;
    return s;
}
inline void rand_seed(uint32_t seed) { rand_state() = seed ? seed : 0x12345678u; }
inline float rand_f32() {
    uint32_t& s = rand_state();
    s ^= s << 13; s ^= s >> 17; s ^= s << 5;
    return (float)(s & 0xFFFFFFu) / (float)0x1000000u;
}

// ---------- Command-line arguments ----------
// Populated by the generated int main(argc, argv).
inline int32_t g_argc = 0;
inline char** g_argv = nullptr;
inline void set_args(int32_t argc, char** argv) { g_argc = argc; g_argv = argv; }
inline int32_t arg_count() { return g_argc; }
inline const char* arg_str(int32_t i) {
    if (g_argv == nullptr || i < 0 || i >= g_argc) return "";
    return g_argv[i];
}

}