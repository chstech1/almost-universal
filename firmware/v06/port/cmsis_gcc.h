/* Compiler primitives used by the pinned SDK's CMSIS Cortex-M3 header. */
#define __ASM __asm
#define __INLINE inline
#define __STATIC_INLINE static inline
#define __STATIC_FORCEINLINE static inline __attribute__((always_inline))
#define __NOP() __asm volatile("nop")
#define __DSB() __asm volatile("dsb" ::: "memory")
#define __ISB() __asm volatile("isb" ::: "memory")
#define __DMB() __asm volatile("dmb" ::: "memory")
