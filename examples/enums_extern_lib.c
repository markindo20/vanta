#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The light cycles off -> dim -> bright -> off. The Vanta side declares
   this as taking and returning its enum Light; both spellings are an
   int32_t at the ABI level. */
int32_t light_next(int32_t mode) { return (mode + 1) % 3; }

/* How many steps of light_next take `from` to `to`? */
int32_t light_steps_to(int32_t from, int32_t to) { return (to - from + 3) % 3; }

#ifdef __cplusplus
}
#endif
