.section .vectors,"ax",@progbits
/* Stock and wrapper calls can spill an eight-register caller window. */
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
window_config: .word 0x00040000
tester: .word smoke_main
.global _start
_start:
    movi.n a2, 1
    wsr a2, windowstart
    l32r a2, window_config
    wsr a2, ps
    rsync
    l32r a1, stack_top
    addi a2, a1, 64
    addi a3, a1, -12
    s32i.n a2, a3, 0
    l32r a8, tester
    callx8 a8
    mov.n a3, a10
    movi.n a2, 1
    simcall

.section .registration_literal,"a",@progbits
    .incbin "callback.bin"

.section .registration,"ax",@progbits
.global stock_registration
stock_registration:
    entry a1, 32
    .incbin "registration.bin"
    retw.n

.section .label_call,"ax",@progbits
.global stock_initial_label
stock_initial_label:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    .incbin "label_call.bin"
    retw.n

.section .group_send,"ax",@progbits
.global stock_group_send
stock_group_send:
    .incbin "group_send.bin"

.section .child_getter,"ax",@progbits
.global stock_get_child
stock_get_child:
    .incbin "child_getter.bin"

.section .event_literals,"a",@progbits
    .word fixture_active_event
    .word 0                       /* Event flags are unused for LV_EVENT_KEY. */

.section .event_dispatch,"ax",@progbits
    .incbin "event_dispatch.bin"

.section .bubble_flag,"a",@progbits
    .word 0x1000

.macro return_value section_name, value
.section .\section_name,"ax",@progbits
    entry a1, 32
    movi.n a2, \value
    retw.n
.endm

return_value event_context, 0
return_value class_preflight, 1
return_value event_bubble, 0

.macro trampoline section_name, symbol, handler
.section .\section_name,"ax",@progbits
.global \symbol
\symbol:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    mov.n a12, a4
    mov.n a13, a5
    call8 \handler
    mov.n a2, a10
    retw.n
.endm

trampoline label_setter, stock_set_text, fixture_set_text
trampoline event_register, fixture_register_entry, fixture_register
trampoline group_focus, fixture_focus_entry, fixture_get_focused

.ifdef SPLASH
.section .fresh_call,"ax",@progbits
.global stock_first_press
stock_first_press:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    .incbin "fresh_call.bin"
    mov.n a2, a10
    retw.n

trampoline stock_image_create, stock_image_create, fixture_image_create
trampoline stock_image_set_source, stock_image_set_source, fixture_image_source
trampoline stock_set_position, stock_set_position, fixture_set_position
trampoline stock_add_flag, stock_add_flag, fixture_add_flag
trampoline stock_clear_flag, stock_clear_flag, fixture_clear_flag
trampoline stock_timer_create, stock_timer_create, fixture_timer_create
trampoline stock_timer_repeat, stock_timer_repeat, fixture_timer_repeat
.endif

.ifdef REPORT
.section .report_dispatch,"ax",@progbits
.global stock_dispatch_report
stock_dispatch_report:
    .incbin "report_dispatch.bin"

return_value stock_reset_idle, 0
trampoline stock_normalize, stock_normalize, fixture_normalize
trampoline stock_ipc_send, stock_ipc_send, fixture_ipc_send
trampoline stock_active_page, stock_active_page, fixture_active_page
trampoline memset, memset, fixture_memset
.endif

.ifdef TILES
trampoline stock_label_create, stock_label_create, fixture_label_create
trampoline stock_set_position, stock_set_position, fixture_set_position
trampoline stock_set_size, stock_set_size, fixture_set_size
trampoline stock_add_flag, stock_add_flag, fixture_add_flag
trampoline stock_clear_flag, stock_clear_flag, fixture_clear_flag
trampoline stock_bg_color, stock_bg_color, fixture_bg_color
trampoline stock_bg_opacity, stock_bg_opacity, fixture_bg_opacity
trampoline stock_text_color, stock_text_color, fixture_text_color
trampoline stock_text_font, stock_text_font, fixture_text_font
trampoline stock_text_align, stock_text_align, fixture_text_align
trampoline stock_pad_top, stock_pad_top, fixture_pad_top
trampoline stock_radius, stock_radius, fixture_radius
.endif

.ifdef COLOR
/* Execute the original RGB565 fill and the final unmodified flush call.
   Stub allocator and panel I/O, with both paths using the same byte writer. */
.section .panel_alloc_literals,"a",@progbits
    .word fixture_panel_alloc, fixture_panel_free
.section .panel_io_literals,"a",@progbits
    .word 0x2580, 0, fixture_panel_window, fixture_panel_write

.section .panel_fill,"ax",@progbits
.global stock_panel_fill
stock_panel_fill:
    .incbin "panel_fill.bin"

.section .panel_flush_tail,"ax",@progbits
.global stock_panel_flush_tail
stock_panel_flush_tail:
    entry a1, 32
    mov.n a4, a2
    mov.n a11, a3
    .incbin "panel_flush_tail.bin"
    retw.n

.section .stock_color_default,"ax",@progbits
.global stock_color_default
stock_color_default:
    .incbin "stock_color_default.bin"
.endif
