#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstddef>
#include <cstdarg>
#include <array>
#include <new>
#include <type_traits>
#include <vector>

namespace vanta {

// ---------- Strings ----------
// `str` is an immutable byte string with reference-counted ownership.
// String literals and argv borrow static storage; str_concat, to_str_*, and
// file_read own a heap buffer that is freed when the last Str referencing it
// dies. Copies are cheap (one refcount bump), and passing a Str never
// invalidates another one.
class Str {
public:
    Str() = default;

    Str(const Str& other)
        : data_(other.data_), len_(other.len_), rep_(other.rep_) {
        if (rep_) rep_->refs += 1;
    }

    Str(Str&& other) noexcept
        : data_(other.data_), len_(other.len_), rep_(other.rep_) {
        other.data_ = "";
        other.len_ = 0;
        other.rep_ = nullptr;
    }

    Str& operator=(const Str& other) {
        if (this != &other) {
            release();
            data_ = other.data_;
            len_ = other.len_;
            rep_ = other.rep_;
            if (rep_) rep_->refs += 1;
        }
        return *this;
    }

    Str& operator=(Str&& other) noexcept {
        if (this != &other) {
            release();
            data_ = other.data_;
            len_ = other.len_;
            rep_ = other.rep_;
            other.data_ = "";
            other.len_ = 0;
            other.rep_ = nullptr;
        }
        return *this;
    }

    ~Str() { release(); }

    // A view of compile-time storage: no allocation and no ownership.
    static Str literal(const char* data, int32_t len) {
        Str out;
        out.data_ = data ? data : "";
        out.len_ = len;
        return out;
    }

    static Str borrow(const char* data) {
        return literal(data, data ? (int32_t)std::strlen(data) : 0);
    }

    // Copy a C string or a byte range into a freshly owned buffer.
    static Str copy(const char* data, int32_t len) {
        if (!data || len <= 0) return Str();
        Rep* rep = static_cast<Rep*>(
            std::malloc(sizeof(Rep) + (size_t)len));
        if (!rep) {
            std::fprintf(stderr, "vanta: string allocation failed\n");
            std::exit(1);
        }
        rep->refs = 1;
        rep->len = len;
        std::memcpy(rep->data, data, (size_t)len);
        rep->data[len] = '\0';
        Str out;
        out.data_ = rep->data;
        out.len_ = len;
        out.rep_ = rep;
        return out;
    }

    static Str from_cstr(const char* data) {
        if (!data) return Str();
        return copy(data, (int32_t)std::strlen(data));
    }

    static Str concat(const Str& a, const Str& b) {
        int64_t total = (int64_t)a.size() + (int64_t)b.size();
        if (total > (int64_t)INT32_MAX) {
            std::fprintf(stderr, "vanta: concatenated string is too large\n");
            std::exit(1);
        }
        int32_t len = (int32_t)total;
        if (len <= 0) return Str();
        Rep* rep = static_cast<Rep*>(
            std::malloc(sizeof(Rep) + (size_t)len));
        if (!rep) {
            std::fprintf(stderr, "vanta: string allocation failed\n");
            std::exit(1);
        }
        rep->refs = 1;
        rep->len = len;
        if (a.size() > 0) std::memcpy(rep->data, a.c_str(), (size_t)a.size());
        if (b.size() > 0) {
            std::memcpy(rep->data + a.size(), b.c_str(), (size_t)b.size());
        }
        rep->data[len] = '\0';
        Str out;
        out.data_ = rep->data;
        out.len_ = len;
        out.rep_ = rep;
        return out;
    }

    const char* c_str() const { return data_ ? data_ : ""; }
    int32_t size() const { return len_; }
    bool empty() const { return len_ == 0; }

    // Extern C functions still take raw const char*; this conversion keeps
    // those calls source-compatible without exposing the representation.
    operator const char*() const { return c_str(); }

private:
    struct Rep {
        uint32_t refs;
        int32_t len;
        char data[1];
    };

    void release() {
        if (rep_ && --rep_->refs == 0) {
            std::free(rep_);
        }
        data_ = "";
        len_ = 0;
        rep_ = nullptr;
    }

    const char* data_ = "";
    int32_t len_ = 0;
    Rep* rep_ = nullptr;
};

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
    ~Arena() { reset(); std::free(data_); }
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
        T* result = static_cast<T*>(
            raw_alloc((uint32_t)(sizeof(T) * (size_t)count),
                      (uint32_t)alignof(T)));
        // Construct non-trivial elements (Str and aggregates containing it)
        // so assignment and destruction are well-defined. Trivial types keep
        // the old uninitialized bump-allocation behaviour.
        if constexpr (std::is_default_constructible<T>::value) {
            for (int32_t i = 0; i < count; i++) {
                new (static_cast<void*>(result + i)) T;
            }
        }
        if constexpr (std::is_default_constructible<T>::value &&
                      !std::is_trivially_destructible<T>::value) {
            if (count > 0) {
                cleanups_.push_back(Cleanup{
                    result, count,
                    [](void* p, int32_t n) {
                        T* items = static_cast<T*>(p);
                        for (int32_t i = n - 1; i >= 0; i--) items[i].~T();
                    }});
            }
        }
        return result;
    }

    void reset() {
        for (auto it = cleanups_.rbegin(); it != cleanups_.rend(); ++it) {
            it->destroy(it->ptr, it->count);
        }
        cleanups_.clear();
        offset_ = 0;
    }

private:
    struct Cleanup {
        void* ptr;
        int32_t count;
        void (*destroy)(void*, int32_t);
    };

    char* data_;
    uint32_t size_;
    uint32_t offset_;
    std::vector<Cleanup> cleanups_;
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

// ---------- Bounds-checked pointer access ----------
// p.at(i, size) compiles down to these. The pointer carries no length, so the
// caller supplies the accessible element count; the helper checks the index
// against it before touching memory. p[i] remains the unchecked escape hatch.
inline void ptr_index_fail(int32_t index, int32_t size, int32_t line) {
    std::fprintf(stderr,
                 "vanta: pointer index %d out of bounds (size %d) at line %d\n",
                 (int)index, (int)size, (int)line);
    std::exit(1);
}

template <typename T>
inline T ptr_at_checked(const T* p, int32_t index, int32_t size, int32_t line) {
    if (index < 0 || index >= size) ptr_index_fail(index, size, line);
    return p[index];
}

template <typename T>
inline T& ptr_at_checked_ref(T* p, int32_t index, int32_t size, int32_t line) {
    if (index < 0 || index >= size) ptr_index_fail(index, size, line);
    return p[index];
}

// ---------- Dynamic lists (List<T>) ----------
// A List<T> is a handle: the value holds a pointer to a small header living
// in an Arena (data pointer, length, capacity). Copying a List copies the
// handle, so every copy sees the same elements. Like ptr<T>, a List is an
// indirection — its elements and its methods are writable through a plain
// `let`; `mut` only controls rebinding. Growth allocates a new block from
// the same arena and copies; nothing is ever freed, so arena.reset()
// invalidates every List that was created from it.
template <typename T>
struct List {
    struct Hdr {
        T* data;
        int32_t len;
        int32_t cap;
        Arena* arena;
    };
    Hdr* h;
};

template <typename T>
inline List<T> list_new(Arena& arena) {
    List<T> xs;
    xs.h = arena.alloc<typename List<T>::Hdr>(1);
    xs.h->data = nullptr;
    xs.h->len = 0;
    xs.h->cap = 0;
    xs.h->arena = &arena;
    return xs;
}

template <typename T>
inline void list_reserve(List<T> xs, int32_t need) {
    if (need <= xs.h->cap) return;
    int32_t cap = xs.h->cap > 0 ? xs.h->cap : 4;
    while (cap < need) cap = (cap > 1073741824) ? need : cap * 2;
    Arena* arena = xs.h->arena;
    T* fresh = arena->alloc<T>(cap);
    for (int32_t i = 0; i < xs.h->len; i++) fresh[i] = xs.h->data[i];
    xs.h->data = fresh;
    xs.h->cap = cap;
}

template <typename T>
inline void list_push(List<T> xs, T value) {
    if (xs.h->len == xs.h->cap) list_reserve<T>(xs, xs.h->len + 1);
    xs.h->data[xs.h->len] = value;
    xs.h->len += 1;
}

template <typename T>
inline T list_pop(List<T> xs, int32_t line) {
    if (xs.h->len == 0) {
        std::fprintf(stderr, "vanta: pop from empty list at line %d\n", (int)line);
        std::exit(1);
    }
    xs.h->len -= 1;
    return xs.h->data[xs.h->len];
}

template <typename T>
inline void list_insert(List<T> xs, int32_t index, T value, int32_t line) {
    if (index < 0 || index > xs.h->len) {
        std::fprintf(stderr,
                     "vanta: insert index %d out of bounds (size %d) at line %d\n",
                     (int)index, (int)xs.h->len, (int)line);
        std::exit(1);
    }
    if (xs.h->len == xs.h->cap) list_reserve<T>(xs, xs.h->len + 1);
    for (int32_t i = xs.h->len; i > index; i--) xs.h->data[i] = xs.h->data[i - 1];
    xs.h->data[index] = value;
    xs.h->len += 1;
}

template <typename T>
inline T list_remove(List<T> xs, int32_t index, int32_t line) {
    if (index < 0 || index >= xs.h->len) {
        std::fprintf(stderr,
                     "vanta: remove index %d out of bounds (size %d) at line %d\n",
                     (int)index, (int)xs.h->len, (int)line);
        std::exit(1);
    }
    T value = xs.h->data[index];
    for (int32_t i = index; i + 1 < xs.h->len; i++) {
        xs.h->data[i] = xs.h->data[i + 1];
    }
    xs.h->len -= 1;
    return value;
}

// list_sort is a stable, O(n log n) merge sort driven by the caller's
// comparator: a function value func(T, T) -> i32 returning negative, zero,
// or positive for less-than, equal, greater-than. Equal elements keep their
// relative order. The scratch block comes from the list's own arena and is
// left behind, exactly like a growth allocation.
template <typename T, typename Cmp>
inline void list_merge(T* data, T* scratch, int32_t lo, int32_t mid, int32_t hi,
                       Cmp cmp) {
    int32_t i = lo, j = mid, k = lo;
    while (i < mid && j < hi) {
        // Ties take the left run — that is what makes the sort stable.
        if (cmp(data[j], data[i]) < 0) scratch[k++] = data[j++];
        else scratch[k++] = data[i++];
    }
    while (i < mid) scratch[k++] = data[i++];
    while (j < hi) scratch[k++] = data[j++];
    for (int32_t x = lo; x < hi; x++) data[x] = scratch[x];
}

template <typename T, typename Cmp>
inline void list_msort(T* data, T* scratch, int32_t lo, int32_t hi, Cmp cmp) {
    if (hi - lo < 2) return;
    int32_t mid = lo + (hi - lo) / 2;
    list_msort<T, Cmp>(data, scratch, lo, mid, cmp);
    list_msort<T, Cmp>(data, scratch, mid, hi, cmp);
    list_merge<T, Cmp>(data, scratch, lo, mid, hi, cmp);
}

template <typename T, typename Cmp>
inline void list_sort(List<T> xs, Cmp cmp) {
    if (xs.h->len < 2) return;
    Arena* arena = xs.h->arena;
    T* scratch = arena->alloc<T>(xs.h->len);
    list_msort<T, Cmp>(xs.h->data, scratch, 0, xs.h->len, cmp);
}

template <typename T>
inline T list_at_checked(List<T> xs, int32_t index, int32_t line) {
    if (index < 0 || index >= xs.h->len) index_fail(index, xs.h->len, line);
    return xs.h->data[index];
}

template <typename T>
inline T& list_at_checked_ref(List<T> xs, int32_t index, int32_t line) {
    if (index < 0 || index >= xs.h->len) index_fail(index, xs.h->len, line);
    return xs.h->data[index];
}

// ---------- String builder (StrBuilder) ----------
// A StrBuilder is a handle onto one growing, NUL-terminated byte buffer in
// an Arena. Append pieces, then call to_str() for the result. to_str() copies
// the current contents into an owned, reference-counted str, so the result
// stays valid after the builder or its arena dies. Like List<T>, a builder is
// an indirection: appends work through a plain `let`.
struct StrBuilder {
    struct Hdr {
        char* data;
        int32_t len;
        int32_t cap;
        Arena* arena;
    };
    Hdr* h;
};

inline StrBuilder strb_new(Arena& arena) {
    StrBuilder b;
    b.h = arena.alloc<StrBuilder::Hdr>(1);
    b.h->cap = 32;
    b.h->data = arena.alloc<char>(32);
    b.h->data[0] = '\0';
    b.h->len = 0;
    b.h->arena = &arena;
    return b;
}

inline void strb_reserve(StrBuilder b, int32_t need) {
    if (need <= b.h->cap) return;
    int32_t cap = b.h->cap;
    while (cap < need) cap = (cap > 1073741824) ? need : cap * 2;
    Arena* arena = b.h->arena;
    char* fresh = arena->alloc<char>(cap);
    std::memcpy(fresh, b.h->data, (size_t)b.h->len + 1);
    b.h->data = fresh;
    b.h->cap = cap;
}

inline void strb_append_n(StrBuilder b, const char* s, int32_t n) {
    strb_reserve(b, b.h->len + n + 1);
    std::memcpy(b.h->data + b.h->len, s, (size_t)n);
    b.h->len += n;
    b.h->data[b.h->len] = '\0';
}

inline void strb_append_str(StrBuilder b, Str s) {
    strb_append_n(b, s.c_str(), s.size());
}

inline void strb_append_i32(StrBuilder b, int32_t v) {
    char tmp[24];
    int n = std::snprintf(tmp, sizeof tmp, "%d", (int)v);
    strb_append_n(b, tmp, n);
}

inline void strb_append_u32(StrBuilder b, uint32_t v) {
    char tmp[24];
    int n = std::snprintf(tmp, sizeof tmp, "%u", (unsigned)v);
    strb_append_n(b, tmp, n);
}

inline void strb_append_f32(StrBuilder b, float v) {
    char tmp[64];
    int n = std::snprintf(tmp, sizeof tmp, "%f", (double)v);
    strb_append_n(b, tmp, n);
}

inline void strb_append_f64(StrBuilder b, double v) {
    char tmp[512];
    int n = std::snprintf(tmp, sizeof tmp, "%lf", v);
    strb_append_n(b, tmp, n);
}

inline void strb_append_bool(StrBuilder b, bool v) {
    if (v) strb_append_n(b, "true", 4);
    else strb_append_n(b, "false", 5);
}

inline void strb_clear(StrBuilder b) {
    b.h->len = 0;
    b.h->data[0] = '\0';
}

inline Str strb_to_str(StrBuilder b) {
    return Str::copy(b.h->data, b.h->len);
}

// ---------- Built-in IO / math ----------
inline void print_i32(int32_t v) { std::printf("%d\n", (int)v); }
inline void print_u32(uint32_t v) { std::printf("%u\n", (unsigned)v); }
inline void print_f32(float v) { std::printf("%f\n", (double)v); }
inline void print_f64(double v) { std::printf("%lf\n", v); }
inline void print_bool(bool v) { std::printf("%s\n", v ? "true" : "false"); }
inline void print_str(Str s) { std::printf("%s\n", s.c_str()); }
inline void print_newline() { std::printf("\n"); }
inline float sqrt_f32(float v) { return std::sqrt(v); }
inline double sqrt_f64(double v) { return std::sqrt(v); }
inline float sin_f32(float v) { return std::sin(v); }
inline double sin_f64(double v) { return std::sin(v); }
inline float cos_f32(float v) { return std::cos(v); }
inline double cos_f64(double v) { return std::cos(v); }
inline float tan_f32(float v) { return std::tan(v); }
inline double tan_f64(double v) { return std::tan(v); }
inline float atan2_f32(float y, float x) { return std::atan2(y, x); }
inline double atan2_f64(double y, double x) { return std::atan2(y, x); }
inline float i32_to_f32(int32_t v) { return (float)v; }
inline int32_t f32_to_i32(float v) { return (int32_t)v; }

// ---------- Output without a trailing newline ----------
inline void write_i32(int32_t v) { std::printf("%d", (int)v); }
inline void write_u32(uint32_t v) { std::printf("%u", (unsigned)v); }
inline void write_f32(float v) { std::printf("%f", (double)v); }
inline void write_f64(double v) { std::printf("%lf", v); }
inline void write_bool(bool v) { std::printf("%s", v ? "true" : "false"); }
inline void write_str(Str s) { std::printf("%s", s.c_str()); }

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
inline bool str_eq(const Str& a, const Str& b) {
    if (a.size() != b.size()) return false;
    if (a.size() == 0) return true;
    return std::memcmp(a.c_str(), b.c_str(), (size_t)a.size()) == 0;
}
inline int32_t str_len(Str s) { return s.size(); }
// strtol/strtod parse a leading number and yield 0 when there is none.
inline int32_t str_to_i32(Str s) {
    return (int32_t)std::strtol(s.c_str(), nullptr, 10);
}
inline float str_to_f32(Str s) {
    return (float)std::strtod(s.c_str(), nullptr);
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

// ---------- String ownership ----------
// str_concat, to_str_*, and file_read return owned Str values. The old
// process-lifetime pool is gone, so str_pool_reset() is retained as a no-op
// for source compatibility; it no longer invalidates anything.
inline void str_pool_reset() {}

inline Str str_concat(Str a, Str b) {
    return Str::concat(a, b);
}

// Substring predicates, written `str_contains`, `str_starts_with`, and
// `str_ends_with` in Vanta source.
inline bool str_contains(Str haystack, Str needle) {
    if (needle.size() <= 0) return true;
    if (needle.size() > haystack.size()) return false;
    const char* h = haystack.c_str();
    const char* n = needle.c_str();
    size_t hn = haystack.size();
    size_t nn = needle.size();
    for (size_t i = 0; i + nn <= hn; i++) {
        if (std::memcmp(h + i, n, nn) == 0) return true;
    }
    return false;
}
inline bool str_starts_with(Str s, Str prefix) {
    if (prefix.size() > s.size()) return false;
    if (prefix.size() == 0) return true;
    return std::memcmp(s.c_str(), prefix.c_str(), prefix.size()) == 0;
}
inline bool str_ends_with(Str s, Str suffix) {
    if (suffix.size() > s.size()) return false;
    if (suffix.size() == 0) return true;
    return std::memcmp(s.c_str() + (s.size() - suffix.size()),
                       suffix.c_str(), suffix.size()) == 0;
}
inline Str to_str_i32(int32_t v) {
    char buf[24];
    int n = std::snprintf(buf, sizeof buf, "%d", (int)v);
    if (n < 0) return Str();
    if ((size_t)n >= sizeof buf) n = (int)sizeof buf - 1;
    return Str::copy(buf, n);
}
inline Str to_str_f32(float v) {
    char buf[64];
    int n = std::snprintf(buf, sizeof buf, "%f", (double)v);
    if (n < 0) return Str();
    if ((size_t)n >= sizeof buf) n = (int)sizeof buf - 1;
    return Str::copy(buf, n);
}
inline Str to_str_bool(bool v) {
    return v ? Str::literal("true", 4) : Str::literal("false", 5);
}

// ---------- File I/O ----------
// Paths and contents are `str` values. file_read returns an owned string, so
// the result stays valid for as long as it is reachable — there is no pool to
// reset. An empty file and a missing file both read as "", so use
// file_exists() when the difference matters. Files are read and written as
// bytes; embedded NUL bytes are preserved in the returned Str and in the
// length reported by str_len.
inline bool file_exists(Str path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return false;
    std::fclose(f);
    return true;
}
inline int32_t file_write(Str path, Str data) {
    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return -1;
    size_t n = std::fwrite(data.c_str(), 1, (size_t)data.size(), f);
    if (std::fclose(f) != 0) return -1;
    return (int32_t)n;
}
inline Str file_read(Str path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) return Str();
    if (std::fseek(f, 0, SEEK_END) != 0) { std::fclose(f); return Str(); }
    long sz = std::ftell(f);
    if (sz < 0 || std::fseek(f, 0, SEEK_SET) != 0) { std::fclose(f); return Str(); }
    if ((uint64_t)sz > (uint64_t)INT32_MAX) {
        std::fprintf(stderr, "vanta: file '%s' is too large for str\n", path.c_str());
        std::exit(1);
    }
    if (sz == 0) { std::fclose(f); return Str(); }
    char* buf = static_cast<char*>(std::malloc((size_t)sz + 1));
    if (!buf) {
        std::fprintf(stderr, "vanta: file read allocation failed\n");
        std::exit(1);
    }
    size_t got = std::fread(buf, 1, (size_t)sz, f);
    std::fclose(f);
    if (got != (size_t)sz) { std::free(buf); return Str(); }
    Str result = Str::copy(buf, (int32_t)sz);
    std::free(buf);
    return result;
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
inline Str arg_str(int32_t i) {
    if (g_argv == nullptr || i < 0 || i >= g_argc) return Str();
    return Str::borrow(g_argv[i]);
}

}


// ---------- Checked integer arithmetic (optional; -DVANTA_CHECKED_ARITH) ----------
// When generated code is compiled with -DVANTA_CHECKED_ARITH, plain + - *
// operators are replaced with helper calls that abort on overflow / wrap.
// Without the flag every helper collapses to the raw operator, so release
// builds pay nothing.
#ifndef VANTA_CK_I32_ADD
#ifdef VANTA_CHECKED_ARITH
#include <limits>
#include <climits>
namespace vanta {
inline int8_t ck_i8_add(int8_t a, int8_t b) {
    long long r = (long long)a + (long long)b;
    if (r < -128 || r > 127) std::abort();
    return (int8_t)r;
}
inline int8_t ck_i8_sub(int8_t a, int8_t b) {
    long long r = (long long)a - (long long)b;
    if (r < -128 || r > 127) std::abort();
    return (int8_t)r;
}
inline int8_t ck_i8_mul(int8_t a, int8_t b) {
    long long r = (long long)a * (long long)b;
    if (r < -128 || r > 127) std::abort();
    return (int8_t)r;
}
inline uint8_t ck_u8_add(uint8_t a, uint8_t b) {
    unsigned long long r = (unsigned long long)a + b;
    if (r > 255) std::abort();
    return (uint8_t)r;
}
inline uint8_t ck_u8_sub(uint8_t a, uint8_t b) {
    if (a < b) std::abort();
    return a - b;
}
inline uint8_t ck_u8_mul(uint8_t a, uint8_t b) {
    unsigned long long r = (unsigned long long)a * b;
    if (r > 255) std::abort();
    return (uint8_t)r;
}
inline int16_t ck_i16_add(int16_t a, int16_t b) {
    long long r = (long long)a + (long long)b;
    if (r < -32768 || r > 32767) std::abort();
    return (int16_t)r;
}
inline int16_t ck_i16_sub(int16_t a, int16_t b) {
    long long r = (long long)a - (long long)b;
    if (r < -32768 || r > 32767) std::abort();
    return (int16_t)r;
}
inline int16_t ck_i16_mul(int16_t a, int16_t b) {
    long long r = (long long)a * (long long)b;
    if (r < -32768 || r > 32767) std::abort();
    return (int16_t)r;
}
inline uint16_t ck_u16_add(uint16_t a, uint16_t b) {
    unsigned long long r = (unsigned long long)a + b;
    if (r > 65535) std::abort();
    return (uint16_t)r;
}
inline uint16_t ck_u16_sub(uint16_t a, uint16_t b) {
    if (a < b) std::abort();
    return a - b;
}
inline uint16_t ck_u16_mul(uint16_t a, uint16_t b) {
    unsigned long long r = (unsigned long long)a * b;
    if (r > 65535) std::abort();
    return (uint16_t)r;
}
inline int32_t ck_i32_add(int32_t a, int32_t b) {
    long long r = (long long)a + (long long)b;
    if (r < INT32_MIN || r > INT32_MAX) std::abort();
    return (int32_t)r;
}
inline int32_t ck_i32_sub(int32_t a, int32_t b) {
    long long r = (long long)a - (long long)b;
    if (r < INT32_MIN || r > INT32_MAX) std::abort();
    return (int32_t)r;
}
inline int32_t ck_i32_mul(int32_t a, int32_t b) {
    long long r = (long long)a * (long long)b;
    if (r < INT32_MIN || r > INT32_MAX) std::abort();
    return (int32_t)r;
}
inline uint32_t ck_u32_add(uint32_t a, uint32_t b) {
    unsigned long long r = (unsigned long long)a + (unsigned long long)b;
    if (r > 0xFFFFFFFFu) std::abort();
    return (uint32_t)r;
}
inline uint32_t ck_u32_sub(uint32_t a, uint32_t b) {
    if (a < b) std::abort();
    return a - b;
}
inline uint32_t ck_u32_mul(uint32_t a, uint32_t b) {
    unsigned long long r = (unsigned long long)a * (unsigned long long)b;
    if (r > 0xFFFFFFFFu) std::abort();
    return (uint32_t)r;
}
}
#define VANTA_CK_I8_ADD(a,b) ::vanta::ck_i8_add((a),(b))
#define VANTA_CK_I8_SUB(a,b) ::vanta::ck_i8_sub((a),(b))
#define VANTA_CK_I8_MUL(a,b) ::vanta::ck_i8_mul((a),(b))
#define VANTA_CK_U8_ADD(a,b) ::vanta::ck_u8_add((a),(b))
#define VANTA_CK_U8_SUB(a,b) ::vanta::ck_u8_sub((a),(b))
#define VANTA_CK_U8_MUL(a,b) ::vanta::ck_u8_mul((a),(b))
#define VANTA_CK_I16_ADD(a,b) ::vanta::ck_i16_add((a),(b))
#define VANTA_CK_I16_SUB(a,b) ::vanta::ck_i16_sub((a),(b))
#define VANTA_CK_I16_MUL(a,b) ::vanta::ck_i16_mul((a),(b))
#define VANTA_CK_U16_ADD(a,b) ::vanta::ck_u16_add((a),(b))
#define VANTA_CK_U16_SUB(a,b) ::vanta::ck_u16_sub((a),(b))
#define VANTA_CK_U16_MUL(a,b) ::vanta::ck_u16_mul((a),(b))
#define VANTA_CK_I32_ADD(a,b) ::vanta::ck_i32_add((a),(b))
#define VANTA_CK_I32_SUB(a,b) ::vanta::ck_i32_sub((a),(b))
#define VANTA_CK_I32_MUL(a,b) ::vanta::ck_i32_mul((a),(b))
#define VANTA_CK_U32_ADD(a,b) ::vanta::ck_u32_add((a),(b))
#define VANTA_CK_U32_SUB(a,b) ::vanta::ck_u32_sub((a),(b))
#define VANTA_CK_U32_MUL(a,b) ::vanta::ck_u32_mul((a),(b))
#else
#define VANTA_CK_I8_ADD(a,b) ((a)+(b))
#define VANTA_CK_I8_SUB(a,b) ((a)-(b))
#define VANTA_CK_I8_MUL(a,b) ((a)*(b))
#define VANTA_CK_U8_ADD(a,b) ((a)+(b))
#define VANTA_CK_U8_SUB(a,b) ((a)-(b))
#define VANTA_CK_U8_MUL(a,b) ((a)*(b))
#define VANTA_CK_I16_ADD(a,b) ((a)+(b))
#define VANTA_CK_I16_SUB(a,b) ((a)-(b))
#define VANTA_CK_I16_MUL(a,b) ((a)*(b))
#define VANTA_CK_U16_ADD(a,b) ((a)+(b))
#define VANTA_CK_U16_SUB(a,b) ((a)-(b))
#define VANTA_CK_U16_MUL(a,b) ((a)*(b))
#define VANTA_CK_I32_ADD(a,b) ((a)+(b))
#define VANTA_CK_I32_SUB(a,b) ((a)-(b))
#define VANTA_CK_I32_MUL(a,b) ((a)*(b))
#define VANTA_CK_U32_ADD(a,b) ((a)+(b))
#define VANTA_CK_U32_SUB(a,b) ((a)-(b))
#define VANTA_CK_U32_MUL(a,b) ((a)*(b))
#endif
#endif
