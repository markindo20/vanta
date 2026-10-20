#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int32_t (*pick_fn)(int32_t);

static int32_t dbl(int32_t x) { return x * 2; }
static int32_t neg(int32_t x) { return -x; }

/* Returns the chosen function, or a null function pointer for anything else. */
pick_fn extret_pick(int32_t which) {
    if (which == 0) return dbl;
    if (which == 1) return neg;
    return 0;
}

#ifdef __cplusplus
}
#endif
