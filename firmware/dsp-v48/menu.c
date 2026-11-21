#include <stdint.h>

enum { HOME = 1, CONTROLS = 2, WIDTH = 240, HEIGHT = 320 };
enum { PAGE_CREATE = 0x2e, PAGE_FOCUS = 0x2f, PAGE_DESTROY = 0x34 };

struct area { int16_t x1, y1, x2, y2; };

/* Two bytes of the alignment word immediately before stock .bss. */
extern struct {
    volatile uint8_t requested;
    uint8_t displayed;
} menu_state;
extern void *volatile stock_page_manager;
extern void *volatile stock_nodev_object;
extern const char *stock_active_page(void);
extern void stock_nodev_event(const uint8_t *event);
extern void stock_normalize(const uint8_t *report);
extern void stock_ipc_send(unsigned tag, const uint8_t *payload, unsigned length);
extern void stock_keypad(void *driver, uint8_t *sample);
extern void stock_invalidate(void *display, const struct area *area);
extern void stock_flush(void *driver, const struct area *area, uint16_t *pixels);

/* See input/keys.tsv in the local stock investigation. Index + 1 is the wire ID. */
static const uint32_t masks[] = {
    0x1, 0x2, 0x4, 0x8, 0x10, 0x40, 0x100, 0x80, 0x20, 0x2000,
    0x200, 0x400, 0x800, 0x4000, 0x20000, 0x1000, 0x10000, 0x8000, 0x40000
};

static int nodev_is_active(void)
{
    if (!stock_nodev_object || !stock_page_manager)
        return 0;
    const char *name = stock_active_page();
    return name && name[0] == 'n' && name[1] == 'o' && name[2] == 'd' &&
           name[3] == 'e' && name[4] == 'v' && name[5] == '\0';
}

void menu_page(const uint8_t *event)
{
    unsigned type = event[8];
    if (type == PAGE_DESTROY) {
        menu_state.requested = 0;
        menu_state.displayed = 0;
    }
    stock_nodev_event(event);
    if ((type == PAGE_CREATE || type == PAGE_FOCUS) && stock_nodev_object &&
        !menu_state.requested)
        menu_state.requested = HOME;
}

static void send_press(unsigned screen, unsigned control, const uint8_t *report)
{
    /* The ARM tag handler copies 0x302 bytes even for this 11-byte content. */
    uint8_t payload[0x302] __attribute__((aligned(4))) = {
        11, 0, 0x7e, 'U', 'R', 1, 1, screen, control,
        report[6], report[7], report[8], report[9]
    };
    stock_ipc_send(19, payload, sizeof payload);
}

void menu_input(const uint8_t *report)
{
    stock_normalize(report);
    if (report[4] != 1)
        return;
    uint32_t mask = (uint32_t)report[0] | ((uint32_t)report[1] << 8) |
                    ((uint32_t)report[2] << 16) | ((uint32_t)report[3] << 24);
    if (!mask || (mask & (mask - 1)) || (mask & (0x10 | 0x40 | 0x4000)))
        return;
    unsigned screen = menu_state.requested;
    if ((screen != HOME && screen != CONTROLS) || !nodev_is_active())
        return;

    for (unsigned i = 0; i < sizeof masks / sizeof masks[0]; ++i) {
        if (mask != masks[i])
            continue;
        unsigned control = i + 1;
        if (screen == HOME && control == 1)
            menu_state.requested = CONTROLS;
        if (screen == CONTROLS && control == 4)
            menu_state.requested = HOME;
        send_press(screen, control, report);
        return;
    }
}

void menu_keypad(void *driver, uint8_t *sample)
{
    static const struct area full = {0, 0, WIDTH - 1, HEIGHT - 1};
    stock_keypad(driver, sample);
    if (!nodev_is_active())
        return;

    /* Keep power and KATA, including any compound reports containing them. */
    if (!(sample[6] & 0x38)) {
        sample[4] = 0;
        sample[5] = 0;
        sample[6] = 0;
        sample[7] = 0;
        sample[14] = 0;
    }
    unsigned screen = menu_state.requested;
    if (screen != menu_state.displayed) {
        menu_state.displayed = screen;
        /* Only the stock LVGL timer thread may enqueue a refresh. */
        stock_invalidate(0, &full);
    }
}

/* Reuse the original five-column uppercase glyphs from ../v06/display.c. */
static const uint8_t glyphs[26][5] = {
    {126,9,9,9,126}, {127,73,73,73,54}, {62,65,65,65,34}, {127,65,65,34,28},
    {127,73,73,73,65}, {127,9,9,9,1}, {62,65,73,73,122}, {127,8,8,8,127},
    {0,65,127,65,0}, {32,64,65,63,1}, {127,8,20,34,65}, {127,64,64,64,64},
    {127,2,12,2,127}, {127,4,8,16,127}, {62,65,65,65,62}, {127,9,9,9,6},
    {62,65,81,33,94}, {127,9,25,41,70}, {38,73,73,73,50}, {1,1,127,1,1},
    {63,64,64,64,63}, {31,32,64,32,31}, {63,64,56,64,63}, {99,20,8,20,99},
    {3,4,120,4,3}, {97,81,73,69,67}
};

#define RGB565(r, g, b) (((r) & 0xf8) << 8 | ((g) & 0xfc) << 3 | (b) >> 3)
#define PANEL_COLOR(r, g, b) (uint16_t)((RGB565(r, g, b) >> 8) | (RGB565(r, g, b) << 8))

struct canvas {
    struct area clip;
    uint16_t *pixels;
    unsigned stride;
};

static void fill(const struct canvas *c, int x, int y, int w, int h, uint16_t color)
{
    int right = x + w - 1, bottom = y + h - 1;
    if (right > c->clip.x2) right = c->clip.x2;
    if (bottom > c->clip.y2) bottom = c->clip.y2;
    if (x < c->clip.x1) x = c->clip.x1;
    if (y < c->clip.y1) y = c->clip.y1;
    if (right < x || bottom < y) return;

    uint16_t *row = c->pixels + (y - c->clip.y1) * c->stride + x - c->clip.x1;
    for (; y <= bottom; ++y) {
        for (int col = 0; col <= right - x; ++col)
            row[col] = color;
        if (y < bottom) row += c->stride;
    }
}

static void label(const struct canvas *c, int x, int y, int scale,
                  uint16_t color, const char *text)
{
    if (y > c->clip.y2 || y + 7 * scale <= c->clip.y1) return;
    for (; *text; ++text, x += 6 * scale) {
        for (int col = 0; col < 5; ++col) {
            unsigned bits = *text >= 'A' && *text <= 'Z' ? glyphs[*text - 'A'][col] : 0;
            if (*text == '-') bits = 8;
            for (int row = 0; row < 7; ++row) {
                if (bits & (1u << row))
                    fill(c, x + col * scale, y + row * scale, scale, scale, color);
            }
        }
    }
}

void menu_render(unsigned screen, const struct area *clip, uint16_t *pixels)
{
    if (clip->x1 < 0 || clip->y1 < 0 || clip->x2 >= WIDTH || clip->y2 >= HEIGHT ||
        clip->x2 < clip->x1 || clip->y2 < clip->y1)
        return;

    const struct canvas c = {*clip, pixels, clip->x2 - clip->x1 + 1};
    const uint16_t background = PANEL_COLOR(18, 25, 53);
    const uint16_t surface = PANEL_COLOR(38, 50, 89);
    const uint16_t text = PANEL_COLOR(248, 248, 252);
    const uint16_t muted = PANEL_COLOR(189, 206, 245);
    const uint16_t accent = screen == HOME ? PANEL_COLOR(131, 163, 255) :
                                            PANEL_COLOR(112, 233, 194);
    const char *const home[] = {"CONTROLS", "-", "-", "-"};
    const char *const controls[] = {"ACTION", "-", "-", "BACK"};
    const char *const *captions = screen == HOME ? home : controls;

    fill(&c, 0, 0, WIDTH, HEIGHT, background);
    label(&c, 20, 38, 4, text, screen == HOME ? "HOME" : "CONTROLS");
    fill(&c, 20, 85, 26, 3, accent);
    fill(&c, 12, 111, 216, 92, surface);
    label(&c, 24, 131, 2, text, screen == HOME ? "LOCAL MENU" : "ACTION A");
    label(&c, 24, 161, 1, muted, screen == HOME ? "HOME ASSISTANT REMOTE" :
                                                   "ASSIGN IN HOME ASSISTANT");
    label(&c, 24, 176, 1, muted, "FIXED CAPTIONS");

    for (int i = 0; i < 4; ++i) {
        const char *caption = captions[i];
        int length = 0;
        while (caption[length]) ++length;
        int center = 30 + 60 * i;
        int enabled = caption[0] != '-';
        const char key[] = {(char)('A' + i), '\0'};
        fill(&c, center - 27, 250, 54, 59, enabled ? surface : background);
        fill(&c, center - 13, 250, 26, 2, enabled ? accent : surface);
        label(&c, center - 5, 263, 2, enabled ? accent : muted, key);
        label(&c, center - (length * 6 - 1) / 2, 287, 1, enabled ? text : muted, caption);
    }
}

void menu_flush(void *driver, const struct area *area, uint16_t *pixels)
{
    unsigned screen = menu_state.displayed;
    if ((screen == HOME || screen == CONTROLS) && nodev_is_active())
        menu_render(screen, area, pixels);
    stock_flush(driver, area, pixels);
}
