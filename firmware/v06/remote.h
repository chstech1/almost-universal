#ifndef UR_REMOTE_H
#define UR_REMOTE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { UR_LIMIT = 8192, UR_SCREENS = 64, UR_CONTROLS = 20 };
enum { UR_PRESS=1, UR_RELEASE, UR_HOLD, UR_REPEAT, UR_TURN, UR_ACTIVATE };
struct ur_text { const uint8_t *bytes; uint8_t len; };
struct ur_view { struct ur_text title, body, soft[4], live; };
/* Called from one application task. Payloads and records use little endian. */
bool ur_write(const uint8_t *data, size_t len);
void ur_disconnect(void);
void ur_status(uint8_t out[14]);
void ur_view(struct ur_view *out);
bool ur_input(uint16_t control, uint8_t kind, int8_t steps, uint8_t event[8]);
bool ur_restore(const uint8_t revision[8], const uint8_t *blob, size_t size);
/* Optional persistence, invoked only for a newly validated complete menu. */
typedef bool (*ur_save_fn)(const uint8_t revision[8], const uint8_t *blob, size_t size);
void ur_set_store(ur_save_fn save);
#endif
