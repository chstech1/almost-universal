.macro expect offset, value
    l32i.n a5, a4, \offset
    movi a6, \value
    beq a5, a6, 1f
    j exit
1:
.endm

.macro check_call target, stage, arg1, arg2, tag
    movi.n a7, 42
    s32i.n a7, a4, 0
    s32i.n a7, a4, 32
    movi.n a10, \arg1
    movi.n a11, \arg2
    l32r a8, \target\()_pointer
    callx8 a8
    expect 0, \stage
    expect 24, \arg1
    expect 28, \arg2
    expect 32, \tag
.endm

.section .start,"ax",@progbits
.p2align 2
stack_top: .word 0x600f0000
valid_windows: .word 0x00040000
uart_pointer: .word uart_fixture
page_tail_pointer: .word page_tail
flush_tail_pointer: .word flush_tail
.ifdef RETENTION
cookie_expected: .word 0x57363852
.endif
.global _start
_start:
    movi a2, 1
    wsr a2, windowstart
    l32r a2, valid_windows
    wsr a2, ps
    rsync
    l32r a1, stack_top
    l32r a4, uart_pointer

    movi.n a3, 1
    call8 app_entry
    expect 0, 69                /* 'E' */
    expect 32, 69               /* observed by stock relocation */

    movi.n a3, 2
    check_call page_tail, 80, 23, 1, 10

.ifdef RETENTION
    movi.n a3, 6
    l32i.n a5, a4, 36
    l32r a6, cookie_expected
    beq a5, a6, 1f
    j exit
1:
    call8 app_entry
    expect 0, 82                /* 'R' */
    expect 32, 82               /* Still calls original relocation. */

    movi.n a3, 7
    movi.n a7, 1
    s32i.n a7, a4, 36
    call8 app_entry
    expect 0, 69                /* A nonzero but incorrect cookie is a miss. */
    expect 32, 69
.endif

    movi.n a3, 3
    check_call flush_tail, 70, 47, 9, 11

    /* Busy status bypasses TX and the stock call still runs. */
    movi.n a3, 4
    movi.n a5, 0
    s32i.n a5, a4, 20
    check_call flush_tail, 42, 21, 12, 11
    expect 12, 3
    expect 20, 0

    /* Divisor access must prevent a write to the shared data register. */
    movi.n a3, 5
    movi a5, 96
    s32i.n a5, a4, 20
    movi a5, 0x83
    s32i.n a5, a4, 12
    check_call page_tail, 42, 31, 1, 10
    expect 20, 96

    movi.n a3, 0
exit:
    movi.n a2, 1
    simcall

.section .entry,"ax",@progbits
app_entry:
    .incbin "entry.bin"
    retw.n

.section .relocate,"ax",@progbits
relocate_uart: .word uart_fixture
    entry a1, 32
    l32r a3, relocate_uart
    l32i.n a2, a3, 0
    s32i.n a2, a3, 32
    retw.n

.section .page,"ax",@progbits
page_tail:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    .incbin "page.bin"

.section .flush,"ax",@progbits
flush_tail:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    .incbin "flush.bin"

.macro stock_stub name, tag
.section .\name,"ax",@progbits
\name\()_uart: .word uart_fixture
    entry a1, 32
    l32r a4, \name\()_uart
    s32i.n a2, a4, 24
    s32i.n a3, a4, 28
    l32i.n a5, a4, 0
    movi.n a6, 42
    bne a5, a6, 1f
    movi.n a5, \tag
    s32i.n a5, a4, 32
1:
    retw.n
.endm

stock_stub stock_clear_page_flag, 10
stock_stub stock_report_versions, 11

.section .extension,"ax",@progbits
    .incbin "extension.bin"

.section .data,"aw",@progbits
uart_fixture: .word 42, 0, 0, 3, 0, 0x20, 0, 0, 0
.ifdef RETENTION
    .word 0
.endif
