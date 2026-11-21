/* Offline fixture for the emitted trace wrappers and fail-stop checkpoints. */
#include <stdint.h>

typedef unsigned (*phase_fn)(unsigned, unsigned, unsigned, unsigned);
extern unsigned site0(unsigned, unsigned, unsigned, unsigned);
extern unsigned site1(unsigned, unsigned, unsigned, unsigned);
extern unsigned site2(unsigned, unsigned, unsigned, unsigned);
extern unsigned site3(unsigned, unsigned, unsigned, unsigned);
extern unsigned site4(unsigned, unsigned, unsigned, unsigned);
extern unsigned site5(unsigned, unsigned, unsigned, unsigned);
extern unsigned site6(unsigned, unsigned, unsigned, unsigned);
extern unsigned site7(unsigned, unsigned, unsigned, unsigned);

extern volatile unsigned uart_fixture[];
extern _Noreturn void exit_fixture(unsigned status);
extern _Noreturn void image_oom(void);
extern _Noreturn void event_oom(void);
extern _Noreturn void timer_oom(void);
extern _Noreturn void palette_oom(void);

enum { TX = 0, LCR = 3, LSR = 5, SCENARIO = 6, TX_IDLE = 0x20, SENTINEL = 0xff };
enum { NORMAL, CROP_NULL, BUSY, DIVISOR, IMAGE_SPIN, EVENT_SPIN, TIMER_SPIN, PALETTE_SPIN };

static unsigned calls;

unsigned fixture_callee(unsigned phase, unsigned a, unsigned b, unsigned c, unsigned d)
{
    if (phase != calls++ || a != 11 || b != 22 || c != 33 || d != 44)
        exit_fixture(1);
    unsigned mode = uart_fixture[SCENARIO];
    unsigned expected = mode == BUSY || mode == DIVISOR ? SENTINEL : 'A' + phase;
    if (uart_fixture[TX] != expected)
        exit_fixture(2);
    if (mode == IMAGE_SPIN && phase == 4)
        image_oom();
    if (mode == EVENT_SPIN && phase == 5)
        event_oom();
    if (mode == TIMER_SPIN && phase == 7)
        timer_oom();
    if (phase == 1 || phase == 6 || (mode == CROP_NULL && phase == 2))
        return 0;
    return 0x12340000u + phase;
}

unsigned phase_trace_fixture(void)
{
    static const phase_fn sites[] = {site0, site1, site2, site3, site4, site5, site6, site7};
    unsigned mode = uart_fixture[SCENARIO];
    if (mode == BUSY)
        uart_fixture[LSR] = 0;
    if (mode == DIVISOR)
        uart_fixture[LCR] = 0x83;
    unsigned end = mode == CROP_NULL ? 3 : sizeof sites / sizeof sites[0];
    for (unsigned i = 0; i < end; ++i) {
        uart_fixture[TX] = SENTINEL;
        unsigned result = sites[i](11, 22, 33, 44);
        unsigned expected = i == 1 || i == 6 || (mode == CROP_NULL && i == 2)
                            ? 0 : 0x12340000u + i;
        unsigned marker = mode == BUSY || mode == DIVISOR ? SENTINEL :
                          (mode == CROP_NULL && i == 2 ? '!' : 'a' + i);
        if (result != expected || uart_fixture[TX] != marker)
            return 3;
    }
    if (mode == PALETTE_SPIN)
        palette_oom();
    if (mode >= IMAGE_SPIN)
        return 4;
    unsigned lcr = mode == DIVISOR ? 0x83 : 3;
    unsigned lsr = mode == BUSY ? 0 : TX_IDLE;
    return calls == end && uart_fixture[LCR] == lcr && uart_fixture[LSR] == lsr ? 0 : 5;
}
