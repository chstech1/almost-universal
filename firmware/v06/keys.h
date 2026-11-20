#ifndef UR_KEYS_H
#define UR_KEYS_H
#include "remote.h"
typedef void (*ur_key_fn)(uint16_t control,uint8_t kind,int8_t steps);
void keys_sample(uint32_t mask,uint8_t wheel,ur_key_fn emit);
void keys_reset(void);
#endif
