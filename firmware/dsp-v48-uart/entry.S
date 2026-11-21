.section .entry_patch,"ax",@progbits
    call8 entry_marker

.section .uart_extension,"ax",@progbits
.p2align 2
uart_address: .word uart_base
message_address: .word message
.global entry_marker
entry_marker:
    entry a1, 32
    l32r a3, uart_address
    memw
    l32i.n a4, a3, 12
    extui a4, a4, 0, 8
    bnei a4, 3, done             /* 8N1, break and divisor access off */

    movi.n a5, 1
    slli a5, a5, 14              /* At most 16,384 status reads. */
wait_ready:
    memw
    l32i.n a4, a3, 20
    bbsi a4, 6, write_marker     /* Resident driver waits for TEMT. */
    addi.n a5, a5, -1
    bnez a5, wait_ready
done:
    retw.n

write_marker:
    l32r a7, message_address
    movi.n a5, 7
write_byte:
    l8ui a4, a7, 0
    memw
    s32i.n a4, a3, 0
    addi.n a7, a7, 1
    addi.n a5, a5, -1
    bnez a5, write_byte
    retw.n

message: .ascii "DSP:E\r\n"
.if . - message != 7
    .error "entry marker must fit the seven-byte send loop"
.endif
