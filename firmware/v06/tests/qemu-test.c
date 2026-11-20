/* Startup and semihosting only for QEMU's MPS2 AN385 machine. */
#include <stdint.h>
int main(void);

static void semihost(uint32_t operation, const void *argument)
{
    register uint32_t r0 __asm__("r0") = operation;
    register const void *r1 __asm__("r1") = argument;
    __asm__ volatile("bkpt 0xab" : "+r"(r0) : "r"(r1) : "memory");
}

void test_print(const char *message)
{
    semihost(4, message); /* SYS_WRITE0 */
    semihost(4, "\n");
}

static __attribute__((noreturn)) void test_exit(uint32_t status)
{
    uint32_t reason[2] = {0x20026, status}; /* ADP_Stopped_ApplicationExit */
    semihost(0x20, reason); /* SYS_EXIT_EXTENDED */
    for (;;) { }
}

void test_fail(const char *where)
{
    test_print(where);
    test_exit(1);
}

static void fault(void)
{
    test_fail("MPS2 test CPU exception");
}

void test_reset(void)
{
    /* -kernel loads this ELF's initialized data; reset-zero RAM supplies .bss. */
    test_exit((uint32_t)main());
}

__attribute__((used, section(".vectors")))
static const uintptr_t vectors[] = {
    0x20010000, (uintptr_t)test_reset, (uintptr_t)fault, (uintptr_t)fault
};

/* LLVM lowers zero-initialization and some struct copies to the ARM EABI helpers. */
void __aeabi_memclr(void *p, unsigned n) { while (n--) *((uint8_t*)p++)=0; }
void __aeabi_memclr4(void *p,unsigned n) { __aeabi_memclr(p,n); }
void __aeabi_memcpy(void *d,const void *s,unsigned n)
{
    uint8_t *dst=d;
    const uint8_t *src=s;
    while(n--) *dst++=*src++;
}
void __aeabi_memcpy4(void *d,const void *s,unsigned n) { __aeabi_memcpy(d,s,n); }
