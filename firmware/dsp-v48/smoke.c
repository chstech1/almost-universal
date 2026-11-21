#include <stdint.h>
#ifdef __XTENSA__
#define STUB(name) __attribute__((section(".stub." #name))) name
#else
#include <stdio.h>
#define STUB(name) name
#endif

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)

struct area { int16_t x1, y1, x2, y2; };
struct report { uint32_t header[2], length; uint8_t data[10]; };

extern void menu_page(const uint8_t *event);
extern void menu_input(const uint8_t *report);
extern void menu_keypad(void *driver, uint8_t *sample);
extern void menu_flush(void *driver, const struct area *clip, uint16_t *pixels);
extern void menu_render(unsigned screen, const struct area *clip, uint16_t *pixels);

#ifdef __XTENSA__
extern void *volatile stock_page_manager, *volatile stock_nodev_object;
extern void stock_dispatch(const struct report *report);
#else
void *volatile stock_page_manager, *volatile stock_nodev_object;
struct { volatile uint8_t requested; uint8_t displayed; } menu_state;
static void stock_dispatch(const struct report *report)
{
    if (report->length == 10) menu_input(report->data);
}
#endif

static const struct area full = {0, 0, 239, 319};
static const char *page;
static unsigned normalized, invalidated, flushed, forwarded, notified, errors;
static unsigned connected, sample_key;
static const uint8_t *expected_report;
static uint8_t packet[14];

const char *STUB(stock_active_page)(void)
{
    if (!stock_page_manager || !stock_nodev_object) ++errors;
    return page;
}

void STUB(stock_nodev_event)(const uint8_t *event)
{
    if (event[8] == 0x2e) stock_nodev_object = &page;
    if (event[8] == 0x34) stock_nodev_object = 0;
}

void STUB(stock_normalize)(const uint8_t *report)
{
    if (report != expected_report) ++errors;
    ++normalized;
}

void STUB(stock_ipc_send)(unsigned tag, const uint8_t *payload, unsigned length)
{
    if (tag != 19 || length != 0x302 || payload[0] != 11 || payload[1] != 0) {
        ++errors;
        return;
    }
    for (unsigned i = 13; i < length; ++i) {
        if (payload[i]) ++errors;
    }
    ++forwarded;
    if (!connected) return;
    ++notified;
    packet[0] = payload[2];
    for (unsigned i = 1; i < 4; ++i) packet[i] = 0;
    for (unsigned i = 4; i < sizeof packet; ++i) packet[i] = payload[i - 1];
}

void STUB(stock_keypad)(void *driver, uint8_t *sample)
{
    (void)driver;
    for (unsigned i = 0; i < 4; ++i) sample[4 + i] = sample_key >> (8 * i);
    sample[14] = sample_key != 0;
}

void STUB(stock_invalidate)(void *display, const struct area *clip)
{
    if (display || clip->x1 != 0 || clip->x2 != 239 || clip->y1 != 0 || clip->y2 != 319)
        ++errors;
    ++invalidated;
}

void STUB(stock_flush)(void *driver, const struct area *clip, uint16_t *pixels)
{
    if (driver != &flushed || !clip || !pixels) ++errors;
    ++flushed;
}

#ifdef __XTENSA__
void *STUB(memset)(void *dest, int ch, unsigned length)
{
    volatile uint8_t *bytes = dest;
    for (unsigned i = 0; i < length; ++i) bytes[i] = ch;
    return dest;
}

void *memcpy(void *dest, const void *source, unsigned length)
{
    volatile uint8_t *bytes = dest;
    const uint8_t *original = source;
    for (unsigned i = 0; i < length; ++i) bytes[i] = original[i];
    return dest;
}
#endif

static void report_key(uint32_t mask, uint8_t phase, uint8_t wheel, uint32_t ticks)
{
    const struct report msg = {{0, 0}, 10, {
        mask, mask >> 8, mask >> 16, mask >> 24, phase, wheel,
        ticks, ticks >> 8, ticks >> 16, ticks >> 24
    }};
    expected_report = msg.data;
    stock_dispatch(&msg);
}

static int is_press(unsigned screen, unsigned id, uint32_t ticks)
{
    const uint8_t expected[] = {0x7e, 0, 0, 0, 'U', 'R', 1, 1, screen, id,
                               ticks, ticks >> 8, ticks >> 16, ticks >> 24};
    for (unsigned i = 0; i < sizeof expected; ++i) {
        if (packet[i] != expected[i]) return 0;
    }
    return 1;
}

static uint16_t complete[240 * 320];

int smoke_main(void)
{
    static const uint32_t keys[] = {
        1, 2, 4, 8, 0x10, 0x40, 0x100, 0x80, 0x20, 0x2000, 0x200, 0x400,
        0x800, 0x4000, 0x20000, 0x1000, 0x10000, 0x8000, 0x40000
    };
    const struct report invalid = {{0, 0}, 9, {1, 0, 0, 0, 1}};
    uint8_t event[9] = {0};
    uint8_t sample[16] = {0};
    uint16_t pixels[8];
    const struct area clip = {24, 131, 26, 132};

    connected = 1;
    stock_dispatch(&invalid);
    report_key(1, 1, 0, 1);
    CHECK(normalized == 1 && forwarded == 0);

    stock_page_manager = &page;
    page = "nodev";
    event[8] = 0x2e;
    menu_page(event);
    CHECK(stock_nodev_object);
    menu_keypad(0, sample);
    CHECK(invalidated == 1);
    report_key(1, 1, 0, 2);
    CHECK(notified == 1 && is_press(1, 1, 2));
    menu_keypad(0, sample);
    CHECK(invalidated == 2);

    report_key(1, 1, 0, 0x12345678);
    CHECK(notified == 2 && is_press(2, 1, 0x12345678));
    for (unsigned phase = 0; phase <= 5; ++phase) {
        if (phase != 1) report_key(1, phase, 0, 3 + phase);
    }
    report_key(0, 0, 1, 9);
    report_key(3, 1, 0, 10);
    report_key(0x4011, 1, 0, 11);
    report_key(0x80000, 1, 0, 12);
    CHECK(notified == 2);

    for (unsigned i = 1; i < sizeof keys / sizeof keys[0]; ++i) {
        unsigned before = notified;
        report_key(keys[i], 1, 0, i + 20);
        if (i == 4 || i == 5 || i == 13) {
            CHECK(notified == before);
        } else {
            CHECK(notified == before + 1 && is_press(i <= 3 ? 2 : 1, i + 1, i + 20));
        }
    }
    CHECK(connected && forwarded == notified);
    menu_keypad(0, sample);
    CHECK(invalidated == 3);

    connected = 0;
    unsigned before = notified;
    report_key(1, 1, 0, 80);
    CHECK(notified == before && forwarded == before + 1);
    connected = 1;
    menu_keypad(0, sample);
    CHECK(invalidated == 4 && notified == before);
    report_key(1, 2, 0, 81);
    report_key(0, 0, 0, 82);
    CHECK(notified == before);
    report_key(1, 1, 0, 83);
    CHECK(notified == before + 1 && is_press(2, 1, 83));

    sample_key = 0x4000;
    menu_keypad(0, sample);
    CHECK(sample[5] == 0 && sample[14] == 0);
    sample_key = 0x104000;
    menu_keypad(0, sample);
    CHECK(sample[5] == 0x40 && sample[6] == 0x10 && sample[14] == 1);

    menu_render(2, &full, complete);
    pixels[0] = pixels[7] = 0x4567;
    menu_flush(&flushed, &clip, pixels + 1);
    CHECK(flushed == 1 && pixels[0] == 0x4567 && pixels[7] == 0x4567);
    for (unsigned row = 0; row < 2; ++row) {
        for (unsigned col = 0; col < 3; ++col) {
            CHECK(pixels[1 + row * 3 + col] == complete[(131 + row) * 240 + 24 + col]);
        }
    }
    const struct area invalid_clip = {-1, 0, 1, 1};
    pixels[1] = 0x4567;
    menu_flush(&flushed, &invalid_clip, pixels + 1);
    CHECK(flushed == 2 && pixels[1] == 0x4567);

    page = "upgrade";
    before = notified;
    report_key(4, 1, 0, 84);
    CHECK(notified == before);
    menu_flush(&flushed, &clip, pixels + 1);
    CHECK(flushed == 3 && pixels[1] == 0x4567);
    sample_key = 0x4000;
    menu_keypad(0, sample);
    CHECK(sample[5] == 0x40 && sample[14] == 1);
    event[8] = 0x34;
    menu_page(event);
    report_key(1, 1, 0, 85);
    CHECK(notified == before && !stock_nodev_object);
    page = "nodev";
    event[8] = 0x2e;
    menu_page(event);
    report_key(1, 1, 0, 86);
    CHECK(notified == before + 1 && is_press(1, 1, 86));
    CHECK(errors == 0 && normalized == 37);
    return 0;
}

#ifndef __XTENSA__
static int preview(unsigned screen, const char *path)
{
    FILE *file = fopen(path, "wb");
    if (!file) return 1;
    menu_render(screen, &full, complete);
    fprintf(file, "P6\n240 320\n255\n");
    for (unsigned i = 0; i < sizeof complete / sizeof complete[0]; ++i) {
        unsigned pixel = complete[i] >> 8 | (complete[i] & 255u) << 8;
        fputc((pixel >> 11) * 255 / 31, file);
        fputc((pixel >> 5 & 63) * 255 / 63, file);
        fputc((pixel & 31) * 255 / 31, file);
    }
    return fclose(file) != 0;
}

int main(int argc, const char **argv)
{
    int result = smoke_main();
    if (result) {
        fprintf(stderr, "smoke failed at line %d\n", result);
        return 1;
    }
    if (argc == 3) return preview(1, argv[1]) || preview(2, argv[2]);
    return argc != 1;
}
#endif
