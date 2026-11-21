.section .vectors,"ax",@progbits
/* Xtensa call8/retw spill and refill the caller's registers on deep calls. */
.org 0x80
    s32e a0, a9, -16
    l32e a0, a1, -12
    s32e a1, a9, -12
    s32e a2, a9, -8
    s32e a3, a9, -4
    s32e a4, a0, -32
    s32e a5, a0, -28
    s32e a6, a0, -24
    s32e a7, a0, -20
    rfwo
.org 0xc0
    l32e a0, a9, -16
    l32e a1, a9, -12
    l32e a2, a9, -8
    l32e a7, a1, -12
    l32e a3, a9, -4
    l32e a4, a7, -32
    l32e a5, a7, -28
    l32e a6, a7, -24
    l32e a7, a7, -20
    rfwu

.section .start,"ax",@progbits
.p2align 2
stack_top: .word 0x600f0000
valid_windows: .word 0x00040000
test_address: .word smoke_main
.global _start
_start:
    movi a2, 1
    wsr a2, windowstart
    l32r a2, valid_windows
    wsr a2, ps
    rsync
    l32r a1, stack_top
    addi a2, a1, 64
    addi a3, a1, -12
    s32i.n a2, a3, 0
    l32r a8, test_address
    callx8 a8
    mov.n a3, a10
    movi a2, 1
    simcall

.section .dispatch,"ax",@progbits
.global stock_dispatch
stock_dispatch:
    .incbin "dispatch.bin"

.section .process,"ax",@progbits
    entry a1, 32
    retw.n
