.section .entry_patch,"ax",@progbits
    call8 mark_entry
.section .page_patch,"ax",@progbits
    call8 mark_page
.section .flush_patch,"ax",@progbits
    call8 mark_flush

.section .extension,"ax",@progbits
.p2align 2
uart_address: .word uart_base
entry_message: .word entry_text
page_message: .word page_text
flush_message: .word flush_text
.ifdef RETENTION
cookie_address: .word retention_word
cookie_value: .word 0x57363852
retained_message: .word retained_text
.endif

.global mark_entry
mark_entry:
    entry a1, 32
    l32r a10, entry_message
.ifdef RETENTION
    l32r a3, cookie_address
    memw
    l32i.n a4, a3, 0
    l32r a5, cookie_value
    bne a4, a5, entry_send
    l32r a10, retained_message
entry_send:
.endif
    call8 send_marker
    retw.n

.p2align 2
.global mark_page
mark_page:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    call8 stock_clear_page_flag
.ifdef RETENTION
    l32r a3, cookie_address
    l32r a4, cookie_value
    memw
    s32i.n a4, a3, 0
.endif
    l32r a10, page_message
    call8 send_marker
    retw.n

.p2align 2
.global mark_flush
mark_flush:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    call8 stock_report_versions
    l32r a10, flush_message
    call8 send_marker
    retw.n

.p2align 2
send_marker:
    entry a1, 32
    l32r a3, uart_address
    memw
    l32i.n a4, a3, 12
    extui a4, a4, 0, 8
    bnei a4, 3, done
    memw
    l32i.n a4, a3, 20
    bbci a4, 5, done             /* Skip if the stock TX FIFO is occupied. */
    movi.n a5, 7
next_byte:
    l8ui a4, a2, 0
    memw
    s32i.n a4, a3, 0
    addi.n a2, a2, 1
    addi.n a5, a5, -1
    bnez a5, next_byte
done:
    retw.n

/* Start on a fresh line and leave the stage letter last. */
entry_text: .ascii "\r\nDSP:E"
page_text: .ascii "\r\nDSP:P"
flush_text: .ascii "\r\nDSP:F"
.ifdef RETENTION
retained_text: .ascii "\r\nDSP:R"
.endif
