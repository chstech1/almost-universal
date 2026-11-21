.section .start,"ax",@progbits
.p2align 2
stack_top: .word 0x600f0000
valid_windows: .word 0x00040000
uart_address: .word uart_fixture
count_address: .word init_count
.global _start
_start:
    movi a2, 1
    wsr a2, windowstart
    l32r a2, valid_windows
    wsr a2, ps
    rsync
    l32r a1, stack_top
    l32r a3, uart_address
    l32r a4, count_address

    /* Idle, normal control register. The FIFO's visible word ends in LF. */
    call8 stock_entry
    movi.n a3, 1
    l32r a5, uart_address
    l32i.n a6, a5, 0
    bnei a6, 10, exit
    l32i.n a6, a4, 0
    bnei a6, 1, exit
    l32i.n a6, a5, 12
    bnei a6, 3, exit
    l32i.n a6, a5, 20
    movi.n a7, 64
    bne a6, a7, exit

    /* Permanently busy. The boot path must continue with no FIFO write. */
    movi.n a7, 42
    s32i.n a7, a5, 0
    movi.n a7, 0
    s32i.n a7, a5, 20
    call8 stock_entry
    movi.n a3, 2
    movi.n a7, 42
    l32i.n a6, a5, 0
    bne a6, a7, exit
    l32i.n a6, a4, 0
    bnei a6, 2, exit

    /* Idle but divisor access enabled. Its low-byte register shares TX. */
    movi a7, 0x83
    s32i.n a7, a5, 12
    movi.n a7, 64
    s32i.n a7, a5, 20
    call8 stock_entry
    movi.n a3, 3
    movi.n a7, 42
    l32i.n a6, a5, 0
    bne a6, a7, exit
    l32i.n a6, a4, 0
    bnei a6, 3, exit
    movi.n a3, 0
exit:
    movi.n a2, 1
    simcall

.section .app,"ax",@progbits
.global stock_entry
stock_entry:
    .incbin "entry.bin"
    retw.n

.section .init_stub,"ax",@progbits
count_literal: .word init_count
    entry a1, 32
    l32r a2, count_literal
    l32i.n a3, a2, 0
    addi.n a3, a3, 1
    s32i.n a3, a2, 0
    retw.n

.section .uart_extension,"ax",@progbits
    .incbin "extension-sim.bin"

.section .data,"aw",@progbits
uart_fixture: .word 42, 0, 0, 3, 0, 0x40
init_count: .word 0
