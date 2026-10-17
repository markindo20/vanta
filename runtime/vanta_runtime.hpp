#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cmath>
#include <cstddef>

namespace vanta {

// ---------- Math types (compact, allocation-free) ----------
struct Vec2 {
    float x, y;
    Vec2() : x(0), y(0) {}
    Vec2(float x_, float y_) : x(x_), y(y_) {}
};
inline Vec2 operator+(Vec2 a, Vec2 b) { return Vec2(a.x + b.x, a.y + b.y); }
inline Vec2 operator-(Vec2 a, Vec2 b) { return Vec2(a.x - b.x, a.y - b.y); }
inline Vec2 operator*(Vec2 a, float s) { return Vec2(a.x * s, a.y * s); }
inline Vec2 operator*(float s, Vec2 a) { return a * s; }
inline float dot(Vec2 a, Vec2 b) { return a.x * b.x + a.y * b.y; }
inline float length(Vec2 a) { return std::sqrt(dot(a, a)); }

struct Vec3 {
    float x, y, z;
    Vec3() : x(0), y(0), z(0) {}
    Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
};
inline Vec3 operator+(Vec3 a, Vec3 b) { return Vec3(a.x + b.x, a.y + b.y, a.z + b.z); }
inline Vec3 operator-(Vec3 a, Vec3 b) { return Vec3(a.x - b.x, a.y - b.y, a.z - b.z); }
inline Vec3 operator*(Vec3 a, float s) { return Vec3(a.x * s, a.y * s, a.z * s); }
inline Vec3 operator*(float s, Vec3 a) { return a * s; }
inline Vec3 operator/(Vec3 a, float s) { return Vec3(a.x / s, a.y / s, a.z / s); }
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

struct Quat {
    float x, y, z, w;
    Quat() : x(0), y(0), z(0), w(1) {}
    Quat(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}
};

struct Matrix4 {
    float m[16];
    Matrix4() {
        for (int i = 0; i < 16; ++i) m[i] = 0.0f;
        m[0] = m[5] = m[10] = m[15] = 1.0f;
    }
};

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

// ---------- Built-in IO / math ----------
inline void print_i32(int32_t v) { std::printf("%d\n", (int)v); }
inline void print_u32(uint32_t v) { std::printf("%u\n", (unsigned)v); }
inline void print_f32(float v) { std::printf("%f\n", (double)v); }
inline void print_f64(double v) { std::printf("%lf\n", v); }
inline void print_bool(bool v) { std::printf("%s\n", v ? "true" : "false"); }
inline void print_newline() { std::printf("\n"); }
inline float sqrt_f32(float v) { return std::sqrt(v); }
inline double sqrt_f64(double v) { return std::sqrt(v); }
inline float i32_to_f32(int32_t v) { return (float)v; }
inline int32_t f32_to_i32(float v) { return (int32_t)v; }

}