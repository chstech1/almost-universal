/* Append-only UART breadcrumbs. Each wrapper preserves arguments and return value. */
.section .phase_trace,"ax",@progbits
.p2align 2
trace_uart: .word uart_base
trace_targets: .word trace_target_table
trace_target_table:
    .word stock_label_create, menu_create, crop_alloc, crop_decode
    .word crop_image, crop_event, crop_source, crop_timer

.macro trace_wrapper name, index
.p2align 2
.global \name
\name:
    entry a1, 32
    movi.n a6, \index
    j trace_call
.endm

trace_wrapper trace_label, 0
trace_wrapper trace_menu, 1
trace_wrapper trace_alloc, 2
trace_wrapper trace_decode, 3
trace_wrapper trace_image, 4
trace_wrapper trace_event, 5
trace_wrapper trace_source, 6
trace_wrapper trace_timer, 7

.p2align 2
trace_call:
    addi a10, a6, 0x41
    call8 trace_byte
    l32r a8, trace_targets
    addx4 a8, a6, a8
    l32i.n a8, a8, 0
    mov.n a10, a2
    mov.n a11, a3
    mov.n a12, a4
    mov.n a13, a5
    callx8 a8
    mov.n a2, a10
    addi a10, a6, 0x61
    bnez.n a2, trace_return
    beqi a6, 1, trace_return  /* void menu initializer */
    beqi a6, 6, trace_return  /* void source setter */
    movi a10, 0x21           /* value-returning call returned zero */
trace_return:
    call8 trace_byte
    retw.n

.p2align 2
trace_byte:
    entry a1, 32
    l32r a3, trace_uart
    memw
    l32i.n a4, a3, 12
    extui a4, a4, 0, 8
    bnei a4, 3, trace_done
    movi a5, 2040
trace_poll:
    memw
    l32i.n a4, a3, 20
    bbsi a4, 5, trace_write  /* THRE, as in the stock checkpoint */
    addi.n a5, a5, -1
    bnez a5, trace_poll
trace_done:
    retw.n
trace_write:
    movi a4, 0x7e
    memw
    s32i.n a4, a3, 0
    memw
    s32i.n a2, a3, 0
    retw.n
