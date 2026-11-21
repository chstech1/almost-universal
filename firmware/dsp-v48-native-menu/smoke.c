#include "menu.h"
#include <stdbool.h>
#ifdef SPLASH
#include "splash.h"
#endif

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

#ifdef ACTION
#define CONTROLS_CAPTION "Controls\n\nA: Action\nD: Back"
#else
#define CONTROLS_CAPTION "Controls\n\nD: Back"
#endif

struct page_objects stock_nodev;
const uint8_t stock_label_class[] = {1};
void *fixture_active_event;

struct event_descriptor {
    void (*callback)(const struct stock_event *);
    const struct page_objects *user_data;
    uint32_t filter;
};

static struct event_descriptor descriptor;
static struct root_spec {
    uint8_t prefix[12];
    struct event_descriptor *slots;
    uint8_t other[10];
    uint8_t count;
} root_spec = {{0}, &descriptor, {0}, 0};
static struct { uint32_t prefix[2]; void *spec; } root = {{0, 0}, &root_spec};

_Static_assert(sizeof(struct event_descriptor) == 12, "stock registration descriptor size");
_Static_assert(offsetof(struct root_spec, slots) == 12, "stock event list offset");
_Static_assert(offsetof(struct root_spec, count) == 26, "stock event count offset");

static struct stock_label label;
static struct stock_label icon;
#ifdef SPLASH
static struct stock_label splash_image;
static void *children[] = {&icon, &label, &splash_image};
#elif defined(HANDHELD_LAYOUT)
static void *children[9] = {&icon, &label};
#else
static void *children[] = {&icon, &label};
#endif
static struct { void **children; uint32_t count; } spec = {children, 2};
static struct { uint32_t prefix[2]; void *spec; } container = {{0, 0}, &spec};
static uint32_t group, changes, errors;
#ifdef HANDHELD_LAYOUT
const uint8_t stock_menu_font[] = {1};
#ifdef HANDHELD_POLISH
const uint8_t stock_compact_font[] = {2};
#endif
static struct layout_label {
    struct stock_label label;
    char text[32];
    int x, y, w, h;
    unsigned hidden, bg, opacity, fg, align, pad_top, radius;
} layout_labels[7];
static unsigned panel_bg, panel_opacity, icon_hidden, initial_label_hidden;
#endif
#ifdef HANDHELD
static char text_storage[112];
#else
static char text_storage[48];
#endif

extern void stock_initial_label(struct stock_label *, const char *);
extern void stock_registration(struct page_objects *);
extern int stock_group_send(void *group, uint32_t key);

static int equal(const char *left, const char *right)
{
    while (*left && *left == *right) {
        ++left;
        ++right;
    }
    return *left == *right;
}

static void text_copy(char *target, unsigned capacity, const char *text)
{
    unsigned i = 0;
    while (i < capacity - 1 && text[i]) {
        target[i] = text[i];
        ++i;
    }
    target[i] = '\0';
    if (text[i])
        ++errors;
}

void fixture_set_text(struct stock_label *target, const char *text)
{
#ifdef HANDHELD_LAYOUT
    for (unsigned i = 0; i < 7; ++i) {
        struct layout_label *child = &layout_labels[i];
        if (target == &child->label) {
            text_copy(child->text, sizeof child->text, text);
            target->text = child->text;
            if (!i)
                ++changes;
            return;
        }
    }
#endif
    if (target != &label || !text) {
        ++errors;
        return;
    }
    text_copy(text_storage, sizeof text_storage, text);
    label.text = text_storage;
#ifdef HANDHELD_LAYOUT
    if (!*text)
        return;
#endif
    ++changes;
}

#ifdef HANDHELD_LAYOUT
struct stock_label *fixture_label_create(void *parent)
{
    if (parent != &container || spec.count >= 9) {
        ++errors;
        return NULL;
    }
    struct stock_label *child = &layout_labels[spec.count - 2].label;
    child->class_pointer = stock_label_class;
    children[spec.count++] = child;
    return child;
}

static struct layout_label *layout_child(void *object, unsigned selector)
{
    for (unsigned i = 0; i < 7; ++i)
        if (object == &layout_labels[i].label && !selector)
            return &layout_labels[i];
    ++errors;
    return &layout_labels[0];
}

void fixture_set_position(void *object, int x, int y)
{
    struct layout_label *child = layout_child(object, 0);
    child->x = x;
    child->y = y;
}

void fixture_set_size(void *object, int width, int height)
{
    struct layout_label *child = layout_child(object, 0);
    child->w = width;
    child->h = height;
}

void fixture_add_flag(void *object, unsigned flag)
{
    if (object == &icon)
        icon_hidden = flag;
    else if (object == &label)
        initial_label_hidden = flag;
    else
        layout_child(object, 0)->hidden = flag;
}

void fixture_clear_flag(void *object, unsigned flag)
{
    if (flag != 1)
        ++errors;
    layout_child(object, 0)->hidden = 0;
}

void fixture_bg_color(void *object, unsigned color, unsigned selector)
{
    if (object == &container && !selector)
        panel_bg = color;
    else
        layout_child(object, selector)->bg = color;
}

void fixture_bg_opacity(void *object, unsigned opacity, unsigned selector)
{
    if (object == &container && !selector)
        panel_opacity = opacity;
    else
        layout_child(object, selector)->opacity = opacity;
}

void fixture_text_font(void *object, const void *font, unsigned selector)
{
    struct layout_label *child = layout_child(object, selector);
#ifdef HANDHELD_POLISH
    const void *expected = child == &layout_labels[0] ? stock_menu_font : stock_compact_font;
#else
    (void)child;
    const void *expected = stock_menu_font;
#endif
    if (font != expected)
        ++errors;
}

#define SET_STYLE(suffix, member) \
    void fixture_##suffix(void *object, unsigned value, unsigned selector) \
    { layout_child(object, selector)->member = value; }
SET_STYLE(text_color, fg)
SET_STYLE(text_align, align)
SET_STYLE(pad_top, pad_top)
SET_STYLE(radius, radius)
#endif

void fixture_register(void *target, void (*callback)(const struct stock_event *), unsigned code,
                      const struct page_objects *user_data)
{
    if (target != &root || code != 13 || user_data != &stock_nodev || !callback)
        ++errors;
    descriptor.callback = callback;
    descriptor.user_data = user_data;
    descriptor.filter = code;
    root_spec.count = 1;
}

void *fixture_get_focused(void *target_group)
{
    if (target_group != &group)
        ++errors;
    return stock_nodev.root;
}

#if defined(ACTION) || defined(HANDHELD)
const char stock_nodev_name[] = "nodev";
void *stock_page_manager = &root;
static const char *active_page = stock_nodev_name;
static uint8_t last_frame[13];
static const uint8_t *expected_raw;
static unsigned normalized, sent;

struct report_message {
    uint32_t header[2];
    uint32_t length;
    uint8_t raw[10];
};

extern void stock_dispatch_report(const struct report_message *report);

void fixture_normalize(const uint8_t *raw)
{
    if (raw != expected_raw)
        ++errors;
    ++normalized;
}

const char *fixture_active_page(void)
{
    return active_page;
}

void *fixture_memset(void *buffer, int byte, size_t length)
{
    volatile uint8_t *out = buffer;
    while (length--)
        *out++ = byte;
    return buffer;
}

void fixture_ipc_send(unsigned tag, const uint8_t *payload, unsigned length)
{
    if (tag != 19 || length != 0x302) {
        ++errors;
        return;
    }
    for (unsigned i = 0; i < sizeof last_frame; ++i)
        last_frame[i] = payload[i];
    for (unsigned i = sizeof last_frame; i < length; ++i)
        if (payload[i])
            ++errors;
    ++sent;
}

static void raw_report(unsigned length, uint32_t buttons, unsigned phase, unsigned wheel, uint32_t ticks)
{
    const struct report_message report = {{0, 0}, length, {
        buttons, buttons >> 8, buttons >> 16, buttons >> 24, phase, wheel,
        ticks, ticks >> 8, ticks >> 16, ticks >> 24
    }};
    expected_raw = report.raw;
    stock_dispatch_report(&report);
}

static int match_frame(uint8_t screen, uint8_t control, uint32_t ticks)
{
    static const uint8_t prefix[] = {11, 0, 0x7e, 'U', 'R', 1, 1};
    for (unsigned i = 0; i < sizeof prefix; ++i)
        if (last_frame[i] != prefix[i])
            return 0;
    uint32_t timestamp = (uint32_t)last_frame[9] | (uint32_t)last_frame[10] << 8 |
                         (uint32_t)last_frame[11] << 16 | (uint32_t)last_frame[12] << 24;
    return last_frame[7] == screen && last_frame[8] == control && timestamp == ticks;
}
#endif

#ifdef HANDHELD
struct handheld_ram handheld_state;

static void press(unsigned mask, uint32_t ticks)
{
    raw_report(10, mask, 1, 0, ticks);
}

#ifdef HANDHELD_LAYOUT
#ifdef HANDHELD_POLISH
enum {
    TitleY = 45, TitleHeight = 32, ModeY = 79,
    RowOne = 104, RowTwo = 171, TileHeight = 61, TilePad = 12, TileRadius = 5,
    IdleFill = 0x1903, FooterX = 1, FooterWidth = 58,
};
#else
enum {
    TitleY = 36, TitleHeight = 26, ModeY = 64,
    RowOne = 89, RowTwo = 149, TileHeight = 54, TilePad = 8, TileRadius = 7,
    IdleFill = 0x2144, FooterX = 0, FooterWidth = 60,
};
#endif

static int geometry(const struct layout_label *item, int x, int y, int width, int height)
{
    return !item->hidden && item->x == x && item->y == y && item->w == width && item->h == height;
}

#ifdef HANDHELD_COLOR
static uint8_t panel_buffer[0x2580];
static uint8_t panel_bytes[2];
static unsigned panel_writes, panel_write_size, panel_windows;

extern void stock_panel_fill(uint16_t color);
extern void stock_panel_flush_tail(const uint16_t *pixels, unsigned count);
extern uint32_t stock_color_default(unsigned property);

void *fixture_panel_alloc(unsigned size)
{
    if (size != sizeof panel_buffer)
        ++errors;
    return panel_buffer;
}

void fixture_panel_free(void *memory)
{
    if (memory != panel_buffer)
        ++errors;
}

void fixture_panel_window(unsigned x1, unsigned y1, unsigned x2, unsigned y2)
{
    if (x1 || y1 || x2 != 239 || y2 != 319)
        ++errors;
    ++panel_windows;
}

void fixture_panel_write(const uint8_t *pixels, unsigned size)
{
    if (size != 2 && size != sizeof panel_buffer) {
        ++errors;
        return;
    }
    if (!panel_writes) {
        panel_bytes[0] = pixels[0];
        panel_bytes[1] = pixels[1];
    }
    for (unsigned i = 0; i < size; ++i)
        if (pixels[i] != panel_bytes[i & 1])
            ++errors;
    panel_write_size = size;
    ++panel_writes;
}

static bool color_matches(uint16_t native, uint16_t rgb565)
{
    panel_writes = panel_windows = 0;
    stock_panel_fill(rgb565);
    if (panel_writes != 16 || panel_windows != 1 || panel_write_size != sizeof panel_buffer)
        return false;
    uint8_t fill_first = panel_bytes[0];
    uint8_t fill_second = panel_bytes[1];

    panel_writes = panel_windows = 0;
    stock_panel_flush_tail(&native, 1);
    return panel_writes == 1 && panel_windows == 0 && panel_write_size == 2 &&
           panel_bytes[0] == fill_first && panel_bytes[1] == fill_second;
}
#else
static bool color_matches(uint16_t native, uint16_t rgb565)
{
    return native == rgb565;
}
#endif

static int smoke_handheld(void)
{
    stock_initial_label(&label, "LCD CHECK.");
    struct layout_label *title = &layout_labels[0];
    struct layout_label *mode = &layout_labels[1];
    struct layout_label *feedback = &layout_labels[2];
    struct layout_label *slots = &layout_labels[3];
#ifdef HANDHELD_COLOR
    uint16_t stock_white = stock_color_default(0x20);
    CHECK(stock_white == 0xffff && color_matches(stock_white, 0xffff));
    CHECK(color_matches(0x00f8, 0xf800));
    CHECK(color_matches(0xe007, 0x07e0) && color_matches(0x1f00, 0x001f));
    CHECK(!color_matches(0x10a2, 0x10a2)); /* Reproduce the mismatched bench palette. */
#endif
    CHECK(spec.count == 9 && color_matches(panel_bg, 0x10a2) && panel_opacity == 255);
    CHECK(icon_hidden && initial_label_hidden && feedback->hidden);
    CHECK(equal(title->text, "Activities") && geometry(title, 14, TitleY, 212, TitleHeight));
    CHECK(equal(mode->text, "Menu mode") && geometry(mode, 14, ModeY, 212, 22));
    CHECK(color_matches(title->fg, 0xf79d) && color_matches(mode->fg, 0xadb5));
    CHECK(equal(slots[0].text, "Watch TV") && geometry(&slots[0], 14, RowOne, 103, TileHeight));
    CHECK(equal(slots[1].text, "Room controls") && geometry(&slots[1], 123, RowOne, 103, TileHeight));
    CHECK(equal(slots[2].text, "Scenes") && geometry(&slots[2], 14, RowTwo, 103, TileHeight) && slots[3].hidden);
    CHECK(color_matches(slots[0].bg, 0xd772) && color_matches(slots[0].fg, 0x1922) &&
          color_matches(slots[1].bg, IdleFill) && color_matches(slots[1].fg, 0xf79d) &&
          slots[1].radius == TileRadius);
    CHECK(slots[0].align == 2 && slots[0].opacity == 255 && slots[0].pad_top == TilePad);

    press(0x80, 1);    /* Right focuses Room controls, Down finds an empty cell. */
    press(0x2000, 2);
    CHECK(color_matches(slots[1].bg, 0xd772) && color_matches(slots[0].bg, IdleFill) && changes == 2);
    press(0x200, 3);   /* Open Room controls, focus Climate, then open it. */
    press(0x80, 4);
    press(0x200, 5);
    CHECK(equal(title->text, "Climate") && equal(slots[3].text, "Raise cool"));
    CHECK(geometry(&slots[3], 123, RowTwo, 103, TileHeight) && geometry(feedback, 14, 253, 212, 21));
    CHECK(equal(feedback->text, "Set up in Home Assistant") && sent == 0);
    press(0x400, 6);
    CHECK(equal(title->text, "Room controls") && color_matches(slots[1].bg, 0xd772) && slots[3].hidden);
    press(0x400, 7);
    CHECK(equal(title->text, "Activities") && color_matches(slots[1].bg, 0xd772));

    press(0x100, 8);
    press(0x200, 9);   /* Open TV mode. */
    raw_report(10, 0x200, 1, 0, 10);
    raw_report(10, 0x200, 2, 0, 11);
    raw_report(10, 0, 0, 0, 12);
    CHECK(equal(title->text, "Watch TV") && equal(mode->text, "TV mode") && sent == 0);
    CHECK(feedback->hidden);
    static const char *const captions[] = {"Input", "Guide", "Menu", "Back"};
    for (unsigned i = 0; i < 4; ++i) {
        CHECK(geometry(&slots[i], i * 60 + FooterX, 274, FooterWidth, 46) &&
              equal(slots[i].text, captions[i]));
        CHECK(color_matches(slots[i].bg, IdleFill) && color_matches(slots[i].fg, 0xf79d) &&
              slots[i].radius == 0 && slots[i].pad_top == 13);
    }

    press(1, 13);      /* A Input sends a single Home Assistant report. */
    CHECK(sent == 1 && match_frame(3, 1, 13));
    press(0x400, 14);  /* Hard Back stays in TV mode. */
    CHECK(sent == 2 && match_frame(3, 12, 14) && equal(mode->text, "TV mode"));
    press(0x800, 15);  /* Hard Home stays in TV mode. */
    CHECK(sent == 3 && match_frame(3, 13, 15) && equal(mode->text, "TV mode"));
    press(8, 16);      /* D returns locally and restores the Watch TV tile. */
    CHECK(equal(title->text, "Activities") && equal(mode->text, "Menu mode"));
    CHECK(geometry(&slots[0], 14, RowOne, 103, TileHeight) &&
          color_matches(slots[0].bg, 0xd772) && slots[3].hidden);
    CHECK(sent == 3 && errors == 0);
    return 0;
}
#else
static int smoke_handheld(void)
{
    stock_initial_label(&label, "LCD CHECK.");
    const char *activities = "Activities\nMenu mode\n\n>Watch TV     Room controls\n Scenes";
    CHECK(changes == 1 && equal(label.text, activities));
    press(1, 1);                  /* Menu A is inactive. */
    press(0x400, 2);              /* Top-level Back is inactive. */
    press(0x100, 3);              /* Left edge. */
    press(0x20, 4);               /* Top edge. */
    CHECK(changes == 1 && sent == 0);

    press(0x80, 5);               /* Focus Room controls. */
    const char *room_focus = "Activities\nMenu mode\n\n Watch TV    >Room controls\n Scenes";
    CHECK(equal(label.text, room_focus));
    press(0x2000, 6);             /* No room tile below. */
    press(0x80, 7);               /* Stop at right edge. */
    CHECK(changes == 2);
    press(0x200, 8);              /* Open Room controls. */
    CHECK(equal(label.text, "Room controls\nMenu mode\n\n>Lights     Climate\n Blinds"));
    press(0x80, 9);
    press(0x200, 10);             /* Open Climate. */
    CHECK(equal(label.text, "Climate\nMenu mode\n\n>Lower heat     Raise heat\n Lower cool     Raise cool\n\nSet up in Home Assistant"));
    press(0x400, 11);             /* Restore Climate focus in Room controls. */
    CHECK(equal(label.text, "Room controls\nMenu mode\n\n Lights    >Climate\n Blinds"));
    press(0x400, 12);             /* Restore Room focus in Activities. */
    CHECK(equal(label.text, room_focus));
    press(0x100, 13);
    CHECK(equal(label.text, activities) && sent == 0);

    raw_report(9, 0x200, 1, 0, 14);
    CHECK(equal(label.text, activities));
    press(0x200, 15);             /* Enter TV without sending OK. */
    const char *tv = "Watch TV\nTV mode\n\nA Input   B Guide\nC Menu   D Back";
    CHECK(equal(label.text, tv) && sent == 0);
    raw_report(10, 0x200, 1, 0, 16); /* Same entry key, new timestamp. */
    raw_report(10, 0x200, 2, 0, 17);
    raw_report(10, 0, 0, 0, 18);
    CHECK(sent == 0);

    static const uint32_t device_keys[] = {1, 2, 4, 0, 0, 0, 0x100, 0x80, 0x20, 0x2000,
                                           0x200, 0x400, 0x800, 0, 0x20000, 0x1000,
                                           0x10000, 0x8000, 0x40000};
    unsigned expected = 0;
    for (unsigned i = 0; i < sizeof device_keys / sizeof device_keys[0]; ++i) {
        if (!device_keys[i])
            continue;
        press(device_keys[i], 0x12345678 + i);
        CHECK(sent == ++expected && match_frame(3, i + 1, 0x12345678 + i));
        CHECK(equal(label.text, tv));
    }
    press(0x10, 21);              /* ON stays with stock. */
    press(0x40, 22);              /* OFF stays with stock. */
    press(0x4000, 23);            /* KATA stays with stock. */
    press(3, 24);                 /* Chord. */
    raw_report(10, 1, 1, 1, 25);  /* Wheel plus A. */
    active_page = "charge";
    press(1, 26);                 /* Inactive view, delegate to stock. */
    active_page = stock_nodev_name;
    press(8, 27);                 /* D returns locally with no sender dependency. */
    CHECK(normalized == 4 && sent == expected && equal(label.text, activities) && errors == 0);
    return 0;
}
#endif
#endif

#ifdef SPLASH
struct splash_ram splash_state;
const uint8_t stock_image_class[] = {2};
static unsigned icon_hidden, splash_hidden, splash_images;
static struct { void (*callback)(void *); unsigned period; int32_t repeats; } timer;

extern int stock_first_press(void *group, uint32_t key);

void *fixture_image_create(void *parent)
{
    if (parent != &container || spec.count != 2)
        ++errors;
    spec.count = 3;
    splash_hidden = 0;
    ++splash_images;
    splash_image.class_pointer = stock_image_class;
    return &splash_image;
}

void fixture_image_source(void *image, const struct image_desc *source)
{
    if (image != &splash_image || !source || source->header != (8 | (48u << 10) | (76u << 21)) ||
        source->data_size != 928 || source->data[3] != 255 || source->data[11] != 255)
        ++errors;
}

void fixture_set_position(void *object, int x, int y)
{
    if (object != &splash_image || x != 96 || y != 105)
        ++errors;
}

void fixture_add_flag(void *object, unsigned flag)
{
    if (flag != 1 || (object != &icon && object != &splash_image))
        ++errors;
    if (object == &icon)
        icon_hidden = 1;
    if (object == &splash_image)
        splash_hidden = 1;
}

void fixture_clear_flag(void *object, unsigned flag)
{
    if (object != &icon || flag != 1)
        ++errors;
    icon_hidden = 0;
}

void *fixture_timer_create(void (*callback)(void *), uint32_t period, void *data)
{
    if (!callback || period != 3000 || data || timer.repeats)
        ++errors;
    timer.callback = callback;
    timer.period = period;
    return &timer;
}

void fixture_timer_repeat(void *target, int32_t repeats)
{
    if (target != &timer || repeats != 1)
        ++errors;
    timer.repeats = repeats;
}

static void service_timer(unsigned elapsed)
{
    if (timer.repeats && elapsed >= timer.period) {
        --timer.repeats;
        timer.callback(&timer);
    }
}

static void new_dsp_boot(void)
{
    splash_state = (struct splash_ram){0, 0};
    spec.count = 2;
    stock_initial_label(&label, "LCD CHECK.");
}

static int smoke_splash(void)
{
    new_dsp_boot();
    CHECK(changes == 1 && icon_hidden && !splash_hidden && equal(label.text, "ALMOST\nUNIVERSAL"));
#ifdef ACTION
    raw_report(10, 1, 1, 0, 8);         /* Fresh A during splash. */
    CHECK(sent == 0 && normalized == 1);
#endif
    stock_first_press(&group, 0x80000);  /* KATA */
    stock_first_press(&group, 0x100000); /* ON */
    stock_first_press(&group, 0x200000); /* OFF */
    stock_group_send(&group, 0x200);    /* Unwrapped repeat. */
    service_timer(2999);
    CHECK(changes == 1);
    service_timer(3000);
    CHECK(changes == 2 && !icon_hidden && splash_hidden && equal(label.text, "Home\n\nA: Controls"));
#ifdef ACTION
    raw_report(10, 1, 1, 0, 15);        /* Home A is local. */
    CHECK(sent == 0);
#endif
    CHECK(stock_first_press(&group, 0x200) == 1);
    CHECK(changes == 3 && equal(label.text, CONTROLS_CAPTION));
#ifdef ACTION
    raw_report(9, 1, 1, 0, 16);         /* Stock length check. */
    CHECK(normalized == 2 && sent == 0);
    raw_report(10, 1, 1, 0, 0x12345678);
    CHECK(sent == 1 && normalized == 3 && match_frame(2, 1, 0x12345678));
    stock_first_press(&group, 0x200);
    stock_group_send(&group, 0x200);
    raw_report(10, 1, 2, 0, 17);        /* Hold. */
    raw_report(10, 1, 0, 0, 18);        /* Release. */
    raw_report(10, 3, 1, 0, 19);        /* A/B chord. */
    raw_report(10, 1, 1, 4, 20);        /* Wheel plus A. */
    raw_report(10, 8, 1, 0, 21);        /* Controls D is local. */
    active_page = "charge";
    raw_report(10, 1, 1, 0, 22);        /* Overlay with nodev objects still live. */
    CHECK(sent == 1 && normalized == 9 && match_frame(2, 1, 0x12345678));
    active_page = stock_nodev_name;
    raw_report(10, 1, 1, 0, 0x87654321);
    CHECK(sent == 2 && match_frame(2, 1, 0x87654321));
#endif
    stock_first_press(&group, 0x1000);
    CHECK(changes == 4 && equal(label.text, "Home\n\nA: Controls"));

    new_dsp_boot();
    CHECK(changes == 5 && equal(label.text, "ALMOST\nUNIVERSAL"));
#ifdef ACTION
    raw_report(10, 1, 1, 0, 32);
#endif
    stock_first_press(&group, 0x200);
    CHECK(changes == 6 && equal(label.text, "Home\n\nA: Controls"));
    stock_group_send(&group, 0x200);
    service_timer(3000);
    CHECK(changes == 6 && !icon_hidden && splash_hidden && !splash_state.fresh_dispatch);
    stock_first_press(&group, 0x200);
    CHECK(changes == 7 && equal(label.text, CONTROLS_CAPTION));
#ifdef ACTION
    CHECK(sent == 2);
#endif

    /* A recreated page on the same DSP boot goes directly to Home. */
    spec.count = 2;
    stock_initial_label(&label, "LCD CHECK.");
    CHECK(changes == 8 && splash_images == 2 && equal(label.text, "Home\n\nA: Controls"));

    new_dsp_boot();
    stock_nodev.root = 0;
    service_timer(3000);
    CHECK(changes == 9 && !fixture_active_event && errors == 0);
    return 0;
}
#endif

int smoke_main(void)
{
    stock_nodev.root = &root;
    stock_nodev.group = &group;
    stock_nodev.container = &container;
    label.class_pointer = stock_label_class;
#ifdef HANDHELD
    return smoke_handheld();
#else
    stock_registration(&stock_nodev);
#ifdef SPLASH
    return smoke_splash();
#else
    stock_initial_label(&label, "LCD CHECK.");
    CHECK(errors == 0 && changes == 1 && equal(label.text, "Home\n\nA: Controls"));

    CHECK(stock_group_send(&group, 0x200) == 1);
    CHECK(!fixture_active_event && changes == 2 && equal(label.text, "Controls\n\nD: Back"));
    stock_group_send(&group, 0x200);     /* A repeat stays in Controls. */
    stock_group_send(&group, 0x80000);   /* KATA remains with the stock path. */
    stock_group_send(&group, 0x200000);  /* OFF remains with the stock path. */
    CHECK(changes == 2);

    stock_group_send(&group, 0x1000);
    CHECK(changes == 3 && equal(label.text, "Home\n\nA: Controls"));
    stock_group_send(&group, 0x1000);    /* D repeat stays in Home. */
    CHECK(changes == 3);

    spec.count = 1;
    stock_group_send(&group, 0x200);
    spec.count = 2;
    label.class_pointer = &icon;
    stock_group_send(&group, 0x200);
    CHECK(changes == 3);
    label.class_pointer = stock_label_class;

    stock_nodev.root = 0;
    CHECK(stock_group_send(&group, 0x200) == 1);
    stock_nodev.root = &root;
    stock_initial_label(&label, "LCD CHECK.");
    CHECK(errors == 0 && changes == 4 && equal(label.text, "Home\n\nA: Controls"));
    return 0;
#endif
#endif
}
