#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

int32_t demo_clamp(int32_t v, int32_t lo, int32_t hi) {
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

float demo_cube(float x) {
    return x * x * x;
}

#ifdef __cplusplus
}
#endif
