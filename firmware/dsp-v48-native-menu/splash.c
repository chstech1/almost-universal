#include "menu.h"
#include "splash.h"

enum { HIDDEN = 1, SPLASH_MS = 3000 };
enum { ICON_WIDTH = 48, ICON_HEIGHT = 76 };

#include "splash_icon.inc"
_Static_assert(sizeof splash_icon == 16 + ICON_WIDTH * ICON_HEIGHT / 4, "indexed icon size");

/* LVGL indexed-2-bit format, width at bit 10 and height at bit 21. */
static const struct image_desc icon = {
    8 | (ICON_WIDTH << 10) | (ICON_HEIGHT << 21), sizeof splash_icon, splash_icon
};

extern const uint8_t stock_image_class[];
extern void *stock_image_create(void *parent);
extern void stock_image_set_source(void *image, const struct image_desc *source);
extern void stock_set_position(void *object, int x, int y);
extern void stock_add_flag(void *object, unsigned flag);
extern void stock_clear_flag(void *object, unsigned flag);
extern void *stock_timer_create(void (*callback)(void *), uint32_t period, void *user_data);
extern void stock_timer_repeat(void *timer, int32_t count);
extern int stock_group_send(void *group, uint32_t key);

int splash_dismiss(struct stock_label *label)
{
    if (!label || label->class_pointer != stock_label_class || !label->text || label->text[0] != 'A')
        return 0;
    void *image = stock_get_child(stock_nodev.container, 2);
    void *stock_icon = stock_get_child(stock_nodev.container, 0);
    if (image && *(const void **)image == stock_image_class)
        stock_add_flag(image, HIDDEN);
    if (stock_icon)
        stock_clear_flag(stock_icon, HIDDEN);
    native_menu_display_home(label);
    return 1;
}

static void splash_timeout(void *timer)
{
    (void)timer;
    if (stock_nodev.root && stock_nodev.container)
        splash_dismiss(stock_get_child(stock_nodev.container, 1));
}

int splash_show(struct stock_label *label)
{
    if (splash_state.shown || !stock_nodev.root || !stock_nodev.container)
        return 0;
    void *stock_icon = stock_get_child(stock_nodev.container, 0);
    if (!stock_icon || stock_get_child(stock_nodev.container, 1) != label)
        return 0;

    splash_state.shown = 1;
    void *image = stock_image_create(stock_nodev.container);
    if (!image)
        return 0;
    void *timer = stock_timer_create(splash_timeout, SPLASH_MS, 0);
    if (!timer) {
        stock_add_flag(image, HIDDEN);
        return 0;
    }
    stock_timer_repeat(timer, 1);
    stock_image_set_source(image, &icon);
    stock_set_position(image, (240 - ICON_WIDTH) / 2, 105);
    stock_add_flag(stock_icon, HIDDEN);
    stock_set_text(label, "ALMOST\nUNIVERSAL");
    return 1;
}

/* Called from the stock keypad's first-press branch only. */
int splash_fresh_group_send(void *group, uint32_t key)
{
    uint8_t previous = splash_state.fresh_dispatch;
    splash_state.fresh_dispatch = 1;
    int result = stock_group_send(group, key);
    splash_state.fresh_dispatch = previous;
    return result;
}
