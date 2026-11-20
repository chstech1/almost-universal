#ifndef UR_BOARD_H
#define UR_BOARD_H
#include "remote.h"
enum { DISPLAY_WIDTH=240, DISPLAY_HEIGHT=320 };
void board_start(void);
void board_redraw(void);
void board_draw_slice(void);
bool board_sample(uint32_t *mask, uint8_t *wheel);
void ur_scanline(const struct ur_view *v, unsigned y, uint16_t pixels[DISPLAY_WIDTH]);
#endif
