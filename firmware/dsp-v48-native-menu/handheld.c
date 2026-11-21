#include "menu.h"
#include <stdbool.h>

enum control { D = 4, LEFT = 7, RIGHT, UP, DOWN, OK, BACK };

enum view {
    ACTIVITIES, ROOM, SCENES, LIGHTS, CLIMATE, BLINDS, TV,
};

enum { TV_WIRE_SCREEN = 3, STOCK_POWER_KEYS = 0x4050 };

struct screen {
    const char *title;
    const char *tiles[4];
    uint8_t count;
    uint8_t parent;
    uint8_t parent_focus;
};

static const struct screen screens[] = {
    [ACTIVITIES] = {"Activities", {"Watch TV", "Room controls", "Scenes"}, 3, ACTIVITIES, 0},
    [ROOM] = {"Room controls", {"Lights", "Climate", "Blinds"}, 3, ACTIVITIES, 1},
    [SCENES] = {"Scenes", {"Movie night", "Evening"}, 2, ACTIVITIES, 2},
    [LIGHTS] = {"Lights", {"Turn on", "Turn off"}, 2, ROOM, 0},
    [CLIMATE] = {"Climate", {"Lower heat", "Raise heat", "Lower cool", "Raise cool"}, 4, ROOM, 1},
    [BLINDS] = {"Blinds", {"Open", "Close", "Stop"}, 3, ROOM, 2},
    [TV] = {"Watch TV", {0}, 0, ACTIVITIES, 0},
};

struct input_report {
    uint32_t buttons;
    uint8_t phase;
    uint8_t wheel;
    uint8_t timestamp[4];
};

_Static_assert(offsetof(struct input_report, timestamp) == 6, "stock timestamp offset");
extern void stock_normalize(const struct input_report *report);
extern void stock_ipc_send(unsigned tag, const uint8_t *payload, unsigned length);
extern const char *stock_active_page(void);
extern const char stock_nodev_name[];
extern void *stock_page_manager;

/* Stock companion bit positions in protocol control ID order, including its reserved keys. */
static const uint8_t control_bits[] = {0, 1, 2, 3, 4, 6, 8, 7, 5, 13, 9, 10, 11, 14, 17, 12, 16, 15, 18};

static unsigned control_id(uint32_t buttons)
{
    for (unsigned i = 0; i < sizeof control_bits; ++i)
        if (buttons == (UINT32_C(1) << control_bits[i]))
            return i + 1;
    return 0;
}

#ifdef HANDHELD_LAYOUT
#ifdef HANDHELD_COLOR
/* The stock flush sends a color word's memory bytes directly to the panel. */
#define NATIVE_RGB565(word) (((word) >> 8) | (((word) & 0xff) << 8))
#else
#define NATIVE_RGB565(word) (word)
#endif

enum {
    HIDDEN = 1, MAIN = 0, LEFT_ALIGN = 1, CENTER_ALIGN = 2,
    PANEL = NATIVE_RGB565(0x10a2), FOCUS = NATIVE_RGB565(0xd772),
    FOCUS_TEXT = NATIVE_RGB565(0x1922), PRIMARY = NATIVE_RGB565(0xf79d),
    SECONDARY = NATIVE_RGB565(0xadb5),
    TITLE_CHILD = 2, MODE_CHILD, FEEDBACK_CHILD, FIRST_SLOT_CHILD,
};

#ifdef HANDHELD_POLISH
enum {
    TILE = NATIVE_RGB565(0x1903), TITLE_Y = 45, TITLE_HEIGHT = 32, MODE_Y = 79,
    GRID_Y = 104, TILE_HEIGHT = 61, ROW_PITCH = 67, TILE_PAD_TOP = 12, TILE_RADIUS = 5,
    CAPTION_INSET = 1, CAPTION_WIDTH = 58,
};
extern const uint8_t stock_compact_font[];
#else
enum {
    TILE = NATIVE_RGB565(0x2144), TITLE_Y = 36, TITLE_HEIGHT = 26, MODE_Y = 64,
    GRID_Y = 89, TILE_HEIGHT = 54, ROW_PITCH = 60, TILE_PAD_TOP = 8, TILE_RADIUS = 7,
    CAPTION_INSET = 0, CAPTION_WIDTH = 60,
};
#endif

extern const uint8_t stock_menu_font[];
extern struct stock_label *stock_label_create(void *parent);
extern void stock_set_position(void *object, int x, int y);
extern void stock_set_size(void *object, int width, int height);
extern void stock_add_flag(void *object, unsigned flag);
extern void stock_clear_flag(void *object, unsigned flag);
extern void stock_bg_color(void *object, uint16_t rgb565, unsigned selector);
extern void stock_bg_opacity(void *object, uint8_t opacity, unsigned selector);
extern void stock_text_color(void *object, uint16_t rgb565, unsigned selector);
extern void stock_text_font(void *object, const void *font, unsigned selector);
extern void stock_text_align(void *object, unsigned alignment, unsigned selector);
extern void stock_pad_top(void *object, int padding, unsigned selector);
extern void stock_radius(void *object, int radius, unsigned selector);

static void place(struct stock_label *label, const char *text, int x, int y,
                  int width, int height)
{
    stock_set_position(label, x, y);
    stock_set_size(label, width, height);
    stock_set_text(label, text);
    stock_clear_flag(label, HIDDEN);
}

static void draw(struct stock_label *label)
{
    void *container = stock_nodev.container;
    struct stock_label *title = stock_get_child(container, TITLE_CHILD);
    struct stock_label *mode = stock_get_child(container, MODE_CHILD);
    struct stock_label *feedback = stock_get_child(container, FEEDBACK_CHILD);
    if (!title || !mode || !feedback) {
        stock_set_text(label, screens[handheld_state.view].title);
        return;
    }

    unsigned view = handheld_state.view;
    const struct screen *screen = &screens[view];
    bool tv = view == TV;
    place(title, screen->title, 14, TITLE_Y, 212, TITLE_HEIGHT);
    place(mode, tv ? "TV mode" : "Menu mode", 14, MODE_Y, 212, 22);
    if (!tv && view >= SCENES)
        place(feedback, "Set up in Home Assistant", 14, 253, 212, 21);
    else
        stock_add_flag(feedback, HIDDEN);

    static const char *const captions[4] = {"Input", "Guide", "Menu", "Back"};
    for (unsigned i = 0; i < 4; ++i) {
        struct stock_label *slot = stock_get_child(container, FIRST_SLOT_CHILD + i);
        if (!slot)
            break;
        if (!tv && i >= screen->count) {
            stock_add_flag(slot, HIDDEN);
            continue;
        }
        bool focused = !tv && i == handheld_state.focus;
        stock_bg_color(slot, focused ? FOCUS : TILE, MAIN);
        stock_text_color(slot, focused ? FOCUS_TEXT : PRIMARY, MAIN);
        stock_pad_top(slot, tv ? 13 : TILE_PAD_TOP, MAIN);
        stock_radius(slot, tv ? 0 : TILE_RADIUS, MAIN);
        if (tv)
            place(slot, captions[i], 60 * i + CAPTION_INSET, 274, CAPTION_WIDTH, 46);
        else
            place(slot, screen->tiles[i], 14 + (i % 2) * 109,
                  GRID_Y + (i / 2) * ROW_PITCH, 103, TILE_HEIGHT);
    }
}

void native_menu_create(struct stock_label *label, const char *stock_caption)
{
    if (!label || label->class_pointer != stock_label_class) {
        if (label)
            stock_set_text(label, stock_caption);
        return;
    }
    void *container = stock_nodev.container;
    if (!container || stock_get_child(container, 1) != label) {
        stock_set_text(label, stock_caption);
        return;
    }

    stock_bg_color(container, PANEL, MAIN);
    stock_bg_opacity(container, 255, MAIN);
    for (unsigned i = TITLE_CHILD; i < FIRST_SLOT_CHILD + 4; ++i) {
        struct stock_label *child = stock_label_create(container);
        if (!child) {
            stock_set_text(label, screens[handheld_state.view].title);
            return;
        }
        stock_add_flag(child, HIDDEN);
#ifdef HANDHELD_POLISH
        /* The default stock face fits captions, wrapped tiles and the setup line. */
        stock_text_font(child, i == TITLE_CHILD ? stock_menu_font : stock_compact_font, MAIN);
#else
        stock_text_font(child, stock_menu_font, MAIN);
#endif
        stock_text_color(child, i == TITLE_CHILD ? PRIMARY : SECONDARY, MAIN);
        stock_text_align(child, i < FIRST_SLOT_CHILD ? LEFT_ALIGN : CENTER_ALIGN, MAIN);
        if (i >= FIRST_SLOT_CHILD)
            stock_bg_opacity(child, 255, MAIN);
    }

    void *icon = stock_get_child(container, 0);
    if (icon)
        stock_add_flag(icon, HIDDEN);
    stock_add_flag(label, HIDDEN);
    stock_set_text(label, "");
    draw(label);
}
#else
static char *copy_text(char *dest, const char *text)
{
    while (*text)
        *dest++ = *text++;
    return dest;
}

static void draw(struct stock_label *label)
{
    if (handheld_state.view == TV) {
        stock_set_text(label, "Watch TV\nTV mode\n\nA Input   B Guide\nC Menu   D Back");
        return;
    }

    const struct screen *screen = &screens[handheld_state.view];
    char text[112];
    char *next = copy_text(text, screen->title);
    next = copy_text(next, "\nMenu mode\n\n");
    for (unsigned i = 0; i < screen->count; ++i) {
        if (i)
            next = copy_text(next, i & 1 ? "    " : "\n");
        *next++ = i == handheld_state.focus ? '>' : ' ';
        next = copy_text(next, screen->tiles[i]);
    }
    if (handheld_state.view >= SCENES)
        next = copy_text(next, "\n\nSet up in Home Assistant");
    *next = '\0';
    stock_set_text(label, text);
}

void native_menu_create(struct stock_label *label, const char *stock_caption)
{
    if (label && label->class_pointer == stock_label_class)
        draw(label);
    else if (label)
        stock_set_text(label, stock_caption);
}
#endif

static void open_view(struct stock_label *label, unsigned view, unsigned focus)
{
    handheld_state.view = view;
    handheld_state.focus = focus;
    /* The stock bus does not forward a reliable key release to the DSP. */
    handheld_state.transition_key = view == TV ? OK : 0;
    draw(label);
}

static void move_focus(struct stock_label *label, unsigned key, unsigned count)
{
    int focus = handheld_state.focus;
    int next = focus;
    if (key == LEFT && (focus & 1))
        next = focus - 1;
    else if (key == RIGHT && !(focus & 1))
        next = focus + 1;
    else if (key == UP)
        next = focus - 2;
    else if (key == DOWN)
        next = focus + 2;
    if (next >= 0 && (unsigned)next < count && next != focus) {
        handheld_state.focus = next;
        draw(label);
    }
}

static __attribute__((noinline)) void send_tv(unsigned control, const uint8_t timestamp[4])
{
    uint8_t payload[0x302] __attribute__((aligned(4))) = {
        11, 0, 0x7e, 'U', 'R', 1, 1, TV_WIRE_SCREEN, control,
        timestamp[0], timestamp[1], timestamp[2], timestamp[3]
    };
    stock_ipc_send(19, payload, sizeof payload);
}

void handheld_report(const struct input_report *report)
{
    /* Keep stock ON, OFF and KATA behavior, including combinations with these keys. */
    if ((report->buttons & STOCK_POWER_KEYS) || !stock_nodev.root || !stock_nodev.container ||
        !stock_page_manager || stock_active_page() != stock_nodev_name) {
        stock_normalize(report);
        return;
    }
    if (report->phase != 1 || report->wheel)
        return;
    unsigned key = control_id(report->buttons);
    if (!key || key == handheld_state.transition_key)
        return;

    struct stock_label *label = stock_get_child(stock_nodev.container, 1);
    if (!label || label->class_pointer != stock_label_class)
        return;

    unsigned view = handheld_state.view;
    const struct screen *screen = &screens[view];
    handheld_state.transition_key = 0;
    if (view == TV) {
        if (key == D)
            open_view(label, screen->parent, screen->parent_focus);
        else
            send_tv(key, report->timestamp);
    } else if (key == BACK && view != ACTIVITIES) {
        open_view(label, screen->parent, screen->parent_focus);
    } else if (key == OK) {
        static const uint8_t destinations[2][3] = {{TV, ROOM, SCENES}, {LIGHTS, CLIMATE, BLINDS}};
        if (view == ACTIVITIES || view == ROOM)
            open_view(label, destinations[view][handheld_state.focus], 0);
    } else {
        move_focus(label, key, screen->count);
    }
}
