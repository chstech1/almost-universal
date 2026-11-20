/* QEMU MPS2 AN385 verification fixture. All addresses describe the emulator. */
ENTRY(test_reset)
SECTIONS {
    .vectors 0 : { KEEP(*(.vectors)) }
    .text : { *(.text*) *(.rodata*) }
    .ARM.exidx : { *(.ARM.exidx*) }
    .data 0x20000000 : { *(.data*) }
    .bss (NOLOAD) : { *(.bss*) *(COMMON) }
}
