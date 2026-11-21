struct splash_ram {
    uint8_t shown;
    uint8_t fresh_dispatch;
};

struct image_desc {
    uint32_t header;
    uint32_t data_size;
    const uint8_t *data;
};

_Static_assert(sizeof(struct splash_ram) <= 4, "startup state uses one alignment word");
_Static_assert(sizeof(struct image_desc) == 12, "stock LVGL IMG descriptor size");

extern struct splash_ram splash_state;

int splash_show(struct stock_label *label);
int splash_dismiss(struct stock_label *label);
void native_menu_display_home(struct stock_label *label);
