#ifndef RADH_NUMBER_THEORY_H
#define RADH_NUMBER_THEORY_H

#include <stdbool.h>
#include <stdint.h>

/* Wspólny helper wewnętrzny; bez dodatkowego symbolu publicznego ABI. */
static inline bool is_prime_u32(uint32_t value)
{
    if (value < 2) {
        return false;
    }
    if (value % 2 == 0) {
        return value == 2;
    }
    /* Dzielenie zamiast divisor * divisor zapobiega przepełnieniu. */
    for (uint32_t divisor = 3; divisor <= value / divisor; divisor += 2) {
        if (value % divisor == 0) {
            return false;
        }
    }
    return true;
}

#endif
