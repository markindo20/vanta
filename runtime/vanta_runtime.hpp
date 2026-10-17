#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstddef>
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

// ---------- String helpers ----------
inline bool str_eq(const char* a, const char* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    return std::strcmp(a, b) == 0;
}

}