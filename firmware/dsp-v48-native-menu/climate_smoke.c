/* Host-only model. This file is outside every DSP build. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

enum {
    CLIMATE = 4, REQUEST = 0x20, SNAPSHOT = 0x21, DELTA = 0x22, CLOSE = 0x23,
    REQUEST_SIZE = 14, HEADER_SIZE = 12, MAX_PAYLOAD = 64, MAX_FIELDS = 8,
};
enum field_type { UNAVAILABLE, BOOLEAN, NUMBER, ENUMERATION, TEMPERATURE };
enum screen_status { CLOSED, WAITING, CURRENT, STALE };

struct field {
    uint8_t type;
    uint8_t value[3];
};

struct readout {
    uint32_t subscription;
    uint16_t sequence;
    uint8_t screen;
    enum screen_status status;
    struct field fields[MAX_FIELDS];
};

static void control_frame(const struct readout *view, uint8_t kind, uint8_t frame[REQUEST_SIZE])
{
    static const uint8_t header[] = {0x7e, 0, 0, 0, 'U', 'R', 1};
    memcpy(frame, header, sizeof header);
    frame[7] = kind;
    frame[8] = view->screen;
    frame[9] = 0;
    for (unsigned i = 0; i < 4; ++i)
        frame[10 + i] = (uint8_t)(view->subscription >> (8 * i));
}

static void request_snapshot(struct readout *view, uint8_t screen, uint32_t subscription,
                             uint8_t frame[REQUEST_SIZE])
{
    if (screen != view->screen)
        memset(view->fields, 0, sizeof view->fields);
    view->screen = screen;
    view->subscription = subscription;
    view->sequence = 0;
    view->status = WAITING;
    control_frame(view, REQUEST, frame);
}

static void close_screen(struct readout *view, uint8_t frame[REQUEST_SIZE])
{
    control_frame(view, CLOSE, frame);
    *view = (struct readout){0};
}

static int32_t signed_le16(const uint8_t *data)
{
    int32_t value = (uint32_t)data[0] | (uint32_t)data[1] << 8;
    return value >= 0x8000 ? value - 0x10000 : value;
}

static bool valid_field(unsigned type, unsigned length, const uint8_t *value)
{
    static const uint8_t lengths[] = {0, 1, 2, 1, 3};
    if (type >= sizeof lengths || length != lengths[type])
        return false;
    if (type == BOOLEAN)
        return value[0] <= 1;
    if (type == TEMPERATURE) {
        int32_t tenths = signed_le16(value + 1);
        return (value[0] == 1 || value[0] == 2) && tenths >= -9999 && tenths <= 9999;
    }
    return true;
}

static bool receive_state(struct readout *view, const uint8_t *data, size_t size)
{
    static const uint8_t header[] = {'U', 'R', 1};
    if (size < HEADER_SIZE || size > MAX_PAYLOAD || memcmp(data, header, sizeof header) != 0 ||
        data[4] != view->screen || !data[5] || data[5] > MAX_FIELDS)
        return false;
    uint32_t subscription = (uint32_t)data[6] | (uint32_t)data[7] << 8 |
                            (uint32_t)data[8] << 16 | (uint32_t)data[9] << 24;
    unsigned sequence = (unsigned)data[10] | (unsigned)data[11] << 8;
    bool snapshot = data[3] == SNAPSHOT && view->status == WAITING && !sequence;
    bool delta = data[3] == DELTA && view->status == CURRENT && sequence > view->sequence;
    if (subscription != view->subscription || (!snapshot && !delta))
        return false;

    struct readout next = *view;
    if (snapshot)
        memset(next.fields, 0, sizeof next.fields);
    unsigned seen = 0;
    size_t offset = HEADER_SIZE;
    for (unsigned i = 0; i < data[5]; ++i) {
        if (size - offset < 3)
            return false;
        unsigned field = data[offset++];
        unsigned type = data[offset++];
        unsigned length = data[offset++];
        if (!field || field > MAX_FIELDS || (seen & (1u << (field - 1))) ||
            length > size - offset || !valid_field(type, length, data + offset))
            return false;
        struct field *slot = &next.fields[field - 1];
        *slot = (struct field){.type = (uint8_t)type};
        memcpy(slot->value, data + offset, length);
        offset += length;
        seen |= 1u << (field - 1);
    }
    if (offset != size)
        return false;
    if (delta && sequence != (unsigned)view->sequence + 1) {
        view->status = STALE;
        return false;
    }
    next.sequence = (uint16_t)sequence;
    next.status = CURRENT;
    *view = next;
    return true;
}

#ifndef CLIMATE_PARSER_ONLY
int main(void)
{
    struct readout view = {0};
    uint8_t request[REQUEST_SIZE];
    const uint8_t expected[] = {0x7e, 0, 0, 0, 'U', 'R', 1, REQUEST, CLIMATE, 0, 0x78, 0x56, 0x34, 0x12};
    const uint8_t initial[] = {'U', 'R', 1, SNAPSHOT, CLIMATE, 1, 0x78, 0x56, 0x34, 0x12,
                               0, 0, 1, TEMPERATURE, 3, 1, 0xd7, 0};
    uint8_t update[] = {'U', 'R', 1, DELTA, CLIMATE, 1, 0x78, 0x56, 0x34, 0x12,
                        1, 0, 1, TEMPERATURE, 3, 1, 0xd6, 0};
    const uint8_t unavailable[] = {'U', 'R', 1, DELTA, CLIMATE, 1, 0x78, 0x56, 0x34, 0x12,
                                   2, 0, 1, UNAVAILABLE, 0};
    const uint8_t fresh[] = {'U', 'R', 1, SNAPSHOT, CLIMATE, 1, 0x79, 0x56, 0x34, 0x12,
                             0, 0, 1, TEMPERATURE, 3, 2, 0xa6, 0xff};
    const uint8_t duplicate[] = {'U', 'R', 1, DELTA, CLIMATE, 2, 0x79, 0x56, 0x34, 0x12, 1, 0,
                                 1, UNAVAILABLE, 0, 1, TEMPERATURE, 3, 1, 0x20, 0};
    const uint8_t synthetic_fields[] = {'U', 'R', 1, SNAPSHOT, 5, 3, 0x7b, 0x56, 0x34, 0x12, 0, 0,
                                        1, BOOLEAN, 1, 1, 2, NUMBER, 2, 75, 0, 3, ENUMERATION, 1, 2};
    const uint8_t synthetic_delta[] = {'U', 'R', 1, DELTA, 5, 1, 0x7b, 0x56, 0x34, 0x12, 1, 0,
                                       2, NUMBER, 2, 60, 0};

    assert(!receive_state(&view, initial, sizeof initial));
    request_snapshot(&view, CLIMATE, 0x12345678, request);
    assert(memcmp(request, expected, sizeof expected) == 0);
    assert(!receive_state(&view, update, sizeof update));
    assert(!receive_state(&view, initial, sizeof initial - 1));
    assert(!receive_state(&view, initial, MAX_PAYLOAD + 1));
    assert(receive_state(&view, initial, sizeof initial));
    assert(view.status == CURRENT && signed_le16(view.fields[0].value + 1) == 215);
    assert(!receive_state(&view, initial, sizeof initial));
    assert(receive_state(&view, update, sizeof update));
    assert(signed_le16(view.fields[0].value + 1) == 214 && view.sequence == 1);
    assert(!receive_state(&view, update, sizeof update));
    assert(receive_state(&view, unavailable, sizeof unavailable));
    assert(view.fields[0].type == UNAVAILABLE);

    update[10] = 4; /* Lost sequence 3 invalidates the current snapshot. */
    assert(!receive_state(&view, update, sizeof update) && view.status == STALE);
    request_snapshot(&view, CLIMATE, 0x12345679, request);
    assert(!receive_state(&view, initial, sizeof initial));
    assert(receive_state(&view, fresh, sizeof fresh));
    assert(view.fields[0].value[0] == 2 && signed_le16(view.fields[0].value + 1) == -90);
    assert(!receive_state(&view, duplicate, sizeof duplicate));
    assert(view.status == CURRENT && view.fields[0].type == TEMPERATURE && view.sequence == 0);

    view.status = STALE; /* Carrier disconnect. Retain only the visible screen's last reading. */
    assert(!receive_state(&view, fresh, sizeof fresh));
    request_snapshot(&view, CLIMATE, 0x1234567a, request);
    assert(view.status == WAITING && signed_le16(view.fields[0].value + 1) == -90);
    assert(!receive_state(&view, fresh, sizeof fresh));
    close_screen(&view, request);
    assert(request[7] == CLOSE && request[8] == CLIMATE && request[10] == 0x7a);
    assert(!receive_state(&view, fresh, sizeof fresh) && view.fields[0].type == UNAVAILABLE);

    /* A synthetic screen exercises the generic decoder without assigning a live entity. */
    request_snapshot(&view, 5, 0x1234567b, request);
    assert(receive_state(&view, synthetic_fields, sizeof synthetic_fields));
    assert(receive_state(&view, synthetic_delta, sizeof synthetic_delta));
    assert(view.fields[0].type == BOOLEAN && view.fields[0].value[0] == 1);
    assert(view.fields[1].type == NUMBER && signed_le16(view.fields[1].value) == 60);
    assert(view.fields[2].type == ENUMERATION && view.fields[2].value[0] == 2);
}
#endif
