#include "menu.h"
#ifdef SPLASH
#include "splash.h"
#endif

enum { LV_EVENT_KEY = 13, SOFT_A = 0x200, SOFT_D = 0x1000 };

static const char home[] = "Home\n\nA: Controls";
#ifdef ACTION
static const char controls[] = "Controls\n\nA: Action\nD: Back";
#else
static const char controls[] = "Controls\n\nD: Back";
#endif

static struct stock_label *native_label(void)
{
    /* Stock creates the icon and then the label as the two container children. */
    struct stock_label *label = stock_get_child(stock_nodev.container, 1);
    if (!label || label->class_pointer != stock_label_class || !label->text)
        return NULL;
    return label;
}

#ifdef SPLASH
void native_menu_display_home(struct stock_label *label)
{
    stock_set_text(label, home);
}
#endif

/* The native nodev create path sizes and aligns the label after this call. */
void native_menu_create(struct stock_label *label, const char *stock_caption)
{
#ifdef SPLASH
    if (label && label->class_pointer == stock_label_class && splash_show(label))
        return;
#endif
    if (label)
        stock_set_text(label, label->class_pointer == stock_label_class ? home : stock_caption);
}

void native_menu_key(const struct stock_event *event)
{
    /* The original callback descriptor belongs to the stock nodev root. */
    if (event->code != LV_EVENT_KEY || event->user_data != &stock_nodev ||
        !stock_nodev.root || event->target != stock_nodev.root ||
        event->current_target != stock_nodev.root || !event->parameter || !stock_nodev.container)
        return;

    uint32_t key = *event->parameter;
#ifdef SPLASH
    /* The stock ordinary-key positions excluding KATA, ON and OFF. */
    if (!splash_state.fresh_dispatch || (key & (key - 1)) || !(key & 0x0fc7fe00u))
        return;
#else
    if (key != SOFT_A && key != SOFT_D)
        return;
#endif

    struct stock_label *label = native_label();
    if (!label)
        return;

#ifdef SPLASH
    if (splash_dismiss(label))
        return;
#endif
    if (key == SOFT_A && label->text[0] == 'H')
        stock_set_text(label, controls);
    else if (key == SOFT_D && label->text[0] == 'C')
        stock_set_text(label, home);
}

#ifdef ACTION
/* The stock message handler validates the ten-byte companion report first. */
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

/* Keep the full stock IPC frame off the stack until an action is accepted. */
static __attribute__((noinline)) void send_controls_a(const uint8_t timestamp[4])
{
    /* Stock ARM copies the entire tag-19 payload before forwarding its 11-byte body. */
    uint8_t payload[0x302] __attribute__((aligned(4))) = {
        11, 0, 0x7e, 'U', 'R', 1, 1, 2, 1,
        timestamp[0], timestamp[1], timestamp[2], timestamp[3]
    };
    stock_ipc_send(19, payload, sizeof payload);
}

void menu_action_report(const struct input_report *report)
{
    stock_normalize(report);
    if (report->buttons != 1 || report->phase != 1 || report->wheel ||
        !stock_nodev.root || !stock_nodev.container || !stock_page_manager ||
        stock_active_page() != stock_nodev_name)
        return;
    struct stock_label *label = native_label();
    if (label && label->text[0] == 'C')
        send_controls_a(report->timestamp);
}
#endif
