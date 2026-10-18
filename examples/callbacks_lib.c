#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Calls f twice: f(f(x)). */
int32_t cbk_apply_twice(int32_t (*f)(int32_t), int32_t x) {
    return f(f(x));
}

/* Calls visit(i, acc) for i in [0, n) — a callback plus user data. */
void cbk_each(int32_t n, void (*visit)(int32_t, int32_t*), int32_t* acc) {
    for (int32_t i = 0; i < n; i++) {
        visit(i, acc);
    }
}

#ifdef __cplusplus
}
#endif
