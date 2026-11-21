#include <stddef.h>
#include <stdint.h>

struct page_objects {
    void *root;
    void *group;
    void *container;
};

struct stock_event {
    const void *target;
    const void *current_target;
    uint8_t code;
    const struct page_objects *user_data;
    const uint32_t *parameter;
};

struct stock_label {
    const void *class_pointer;
    uint8_t object_data[0x20];
    const char *text;
};

_Static_assert(sizeof(void *) == 4, "v4.8 uses the 32-bit Xtensa ABI");
_Static_assert(offsetof(struct page_objects, container) == 8, "nodev container offset");
_Static_assert(offsetof(struct stock_event, code) == 8, "stock event code offset");
_Static_assert(offsetof(struct stock_event, user_data) == 12, "stock user data offset");
_Static_assert(offsetof(struct stock_event, parameter) == 16, "stock parameter offset");
_Static_assert(offsetof(struct stock_label, text) == 0x24, "stock label text offset");

extern struct page_objects stock_nodev;
extern const uint8_t stock_label_class[];
extern void stock_set_text(struct stock_label *label, const char *text);
extern void *stock_get_child(void *parent, int index);

#ifdef HANDHELD
/* The native menu can use one alignment word cleared at DSP startup. */
struct handheld_ram {
    uint8_t view;
    uint8_t focus;
    uint8_t transition_key;
};

_Static_assert(sizeof(struct handheld_ram) <= 4, "handheld state fits the alignment word");
extern struct handheld_ram handheld_state;
#endif
