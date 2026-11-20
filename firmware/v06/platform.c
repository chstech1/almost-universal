#include "pskeys.h"
#include "driver_syscntl.h"

/* Leave the device address, RF calibration and loader options supplied by ROM. */
void user_custom_parameters(void)
{
    pskeys.stack_mode=STACK_MODE_BLE;
    pskeys.enable_profiles=0;
}
void user_entry_before_stack_init(void) { system_sleep_disable(); }
void user_entry_before_sleep_imp(void) {}
void user_entry_after_sleep_imp(void) {}
void cdc_isr_ram(void) {}
/* Development image has no DSP audio or USB application. */

void *memcpy(void *destination,const void *source,size_t length)
{
    unsigned char *to=destination;
    const unsigned char *from=source;
    while (length--) *to++=*from++;
    return destination;
}
