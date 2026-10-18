#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Every parameter keeps its exact width: the C ABI passes them as written. */
int32_t narrow_sum(int8_t a, uint8_t b, int16_t c, uint16_t d) {
    return (int32_t)a + (int32_t)b + (int32_t)c + (int32_t)d;
}

/* Returns a uint8_t: the generated C++ function has a uint8_t return type. */
uint8_t narrow_low(uint32_t x) { return (uint8_t)x; }

/* Hands the pointer back as void*, the way C APIs carry user data. */
void* narrow_erase(int32_t* p) { return p; }

/* Mirrors the Pixel struct of the example — field for field, width for
   width. If the generated C++ struct did not lay out the same way (a u8
   widened to int32, say), these sums would be garbage. */
typedef struct {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint32_t hits;
} pixel_mirror_t;

int32_t narrow_pixel_sum(void* p) {
    pixel_mirror_t* px = (pixel_mirror_t*)p;
    return (int32_t)px->r + (int32_t)px->g + (int32_t)px->b;
}

uint32_t narrow_pixel_hits(void* p) {
    pixel_mirror_t* px = (pixel_mirror_t*)p;
    return px->hits;
}

#ifdef __cplusplus
}
#endif
