ENTRY(app_entry)
MEMORY {
  XIP (rx) : ORIGIN = 0x01003000, LENGTH = 224K
  VECT (r) : ORIGIN = 0x20000000, LENGTH = 0xc0
  DATES (r) : ORIGIN = 0x20004fe0, LENGTH = 0x20
  RAM (rw) : ORIGIN = 0x20005000, LENGTH = 76K
}
SECTIONS {
  .text : {
    KEEP(*(entry_code)) *(.text .text.* i.*) *(.rodata .rodata.* .constdata*)
  } > XIP
  .vectors 0x20000000 : AT(ALIGN(LOADADDR(.text)+SIZEOF(.text),4)) { KEEP(*(.vectors)) } > VECT
  .ramcode ORIGIN(RAM) : AT(ALIGN(LOADADDR(.vectors)+SIZEOF(.vectors),4)) { *(ram_code) . = ALIGN(4); } > RAM
  .data : AT(ALIGN(LOADADDR(.ramcode)+SIZEOF(.ramcode),4)) { *(.data .data.*) } > RAM
  .bss (NOLOAD) : AT(ADDR(.bss)) { *(.bss .bss.* COMMON) } > RAM
  .time 0x20004fe0 : AT(ALIGN(LOADADDR(.data)+SIZEOF(.data),4)) { LONG(0); LONG(0); LONG(0); } > DATES
  .date 0x20004ff0 : AT(LOADADDR(.time)+SIZEOF(.time)) { LONG(0); LONG(0); LONG(0); } > DATES
  /DISCARD/ : { *(.ARM.exidx* .ARM.extab* .comment .note*) }
}
