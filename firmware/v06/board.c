#include "board.h"
#include "sdk_ports.h"
#include "driver_ssp.h"
static uint16_t pixels[DISPLAY_WIDTH];
static uint8_t wire_pixels[2*DISPLAY_WIDTH];
static void lcd_select(uint8_t level)
{
    gpio_set_pin_value(GPIO_PORT_B, GPIO_BIT_0, level);
}

static void lcd_command(uint8_t command)
{
    gpio_set_pin_value(GPIO_PORT_A, GPIO_BIT_6, 0);
    ssp_send_data(&command, 1);
    gpio_set_pin_value(GPIO_PORT_A, GPIO_BIT_6, 1);
}

static void output(enum system_port_t port, enum system_port_bit_t bit, uint8_t level)
{
    gpio_set_pin_value(port, bit, level);
    gpio_set_dir(port, bit, GPIO_DIR_OUT);
    system_set_port_mux(port, bit, 0);
}

static void init_lcd(void)
{
    /* Command, parameter count, parameter bytes; register values from V46 +0x8240. */
    static const uint8_t registers[] = {
        0x36, 1, 0xc0, 0x3a, 1, 0x55,
        0xb2, 5, 0x0c, 0x0c, 0, 0x33, 0x33,
        0xb7, 1, 0x56, 0xbb, 1, 0x20, 0xc0, 1, 0x2c, 0xc2, 1, 1,
        0xc3, 1, 0x0f, 0xc4, 1, 0x20, 0xc6, 1, 0x0f,
        0xd0, 2, 0xa4, 0xa1, 0xd6, 1, 0xa1,
        0xe0, 14, 0xf0, 0, 6, 6, 7, 5, 0x30, 0x44, 0x48, 0x38, 0x11, 0x10, 0x2e, 0x34,
        0xe1, 14, 0xf0, 0x0a, 0x0e, 0x0d, 0x0b, 0x27, 0x2f, 0x44, 0x47, 0x35, 0x12, 0x12, 0x2c, 0x32,
        0x35, 1, 0, 0x21, 0, 0x29, 0,
    };
    output(GPIO_PORT_A, GPIO_BIT_7, 0); /* Backlight off during first frame. */
    output(GPIO_PORT_B, GPIO_BIT_0, 1);
    output(GPIO_PORT_A, GPIO_BIT_6, 1);
    output(GPIO_PORT_B, GPIO_BIT_3, 1);
    system_set_port_mux(GPIO_PORT_A, GPIO_BIT_0, PORTA0_FUNC_SSP_SCLK);
    system_set_port_mux(GPIO_PORT_A, GPIO_BIT_2, PORTA2_FUNC_SSP_MOSI);
    system_set_port_mux(GPIO_PORT_A, GPIO_BIT_3, PORTA3_FUNC_SSP_MISO);
    ssp_init(8, SSP_FRAME_MOTO, SSP_MASTER_MODE, 2000000, 2, lcd_select);

    co_delay_100us(100);
    gpio_set_pin_value(GPIO_PORT_B, GPIO_BIT_3, 0);
    co_delay_100us(100);
    gpio_set_pin_value(GPIO_PORT_B, GPIO_BIT_3, 1);
    co_delay_100us(100);
    lcd_command(0x11); /* Exit sleep. */
    co_delay_100us(1200);
    for (size_t i = 0; i < sizeof(registers); ) {
        lcd_command(registers[i++]);
        unsigned count = registers[i++];
        while (count--) {
            uint8_t data = registers[i++];
            ssp_send_data(&data, 1);
        }
    }
}

static unsigned next_row;

void board_redraw(void) { next_row = 0; }

void board_draw_slice(void)
{
    if (next_row >= DISPLAY_HEIGHT) return;
    unsigned end = next_row + 8;
    struct ur_view view;
    ur_view(&view);
    uint8_t columns[] = {0, 0, (DISPLAY_WIDTH - 1) >> 8, (DISPLAY_WIDTH - 1) & 255};
    uint8_t rows[] = {(uint8_t)(next_row >> 8), (uint8_t)next_row,
                      (uint8_t)((end - 1) >> 8), (uint8_t)(end - 1)};
    lcd_command(0x2a);
    ssp_send_data(columns, sizeof(columns));
    lcd_command(0x2b);
    ssp_send_data(rows, sizeof(rows));
    lcd_command(0x2c);
    for (; next_row < end; ++next_row) {
        ur_scanline(&view, next_row, pixels);
        for (unsigned x = 0; x < DISPLAY_WIDTH; ++x) {
            wire_pixels[2*x] = (uint8_t)(pixels[x] >> 8);
            wire_pixels[2*x + 1] = (uint8_t)pixels[x];
        }
        ssp_send_data(wire_pixels, sizeof(wire_pixels));
    }
}

/* High is a released input. This preserves a companion's ability to ACK or stretch. */
static void line(enum system_port_bit_t bit, bool high)
{
    if (!high)
        gpio_set_pin_value(GPIO_PORT_C, bit, 0);
    gpio_set_dir(GPIO_PORT_C, bit, high ? GPIO_DIR_IN : GPIO_DIR_OUT);
}

static bool raise_clock(void)
{
    line(GPIO_BIT_0, true);
    for (unsigned wait = 0; wait < 100; ++wait) {
        co_delay_10us(1);
        if (gpio_get_pin_value(GPIO_PORT_C, GPIO_BIT_0))
            return true;
    }
    return false;
}

static bool start(void)
{
    line(GPIO_BIT_1, true);
    co_delay_10us(1);
    if (!raise_clock() || !gpio_get_pin_value(GPIO_PORT_C, GPIO_BIT_1))
        return false;
    line(GPIO_BIT_1, false);
    co_delay_10us(1);
    line(GPIO_BIT_0, false);
    return true;
}

static bool stop(void)
{
    line(GPIO_BIT_1, false);
    co_delay_10us(1);
    bool clock_high = raise_clock();
    line(GPIO_BIT_1, true);
    co_delay_10us(1);
    return clock_high && gpio_get_pin_value(GPIO_PORT_C, GPIO_BIT_1);
}

static bool transfer_bit(bool released, uint8_t *sample)
{
    line(GPIO_BIT_1, released);
    co_delay_10us(1);
    if (!raise_clock())
        return false;
    if (sample)
        *sample = gpio_get_pin_value(GPIO_PORT_C, GPIO_BIT_1);
    line(GPIO_BIT_0, false);
    co_delay_10us(1);
    return true;
}

static bool send_byte(uint8_t value)
{
    for (unsigned mask = 0x80; mask; mask >>= 1)
        if (!transfer_bit((value & mask) != 0, NULL))
            return false;
    uint8_t nack;
    return transfer_bit(true, &nack) && !nack;
}

static bool read_register(uint8_t reg, uint8_t *bytes, size_t length)
{
    bool ok = start();
    if (ok)
        ok = send_byte(0xae) && send_byte(reg) && start() && send_byte(0xaf);
    for (size_t i = 0; ok && i < length; ++i) {
        uint8_t value = 0, bit;
        for (unsigned j = 0; j < 8; ++j) {
            ok = transfer_bit(true, &bit);
            if (!ok)
                break;
            value = (uint8_t)((value << 1) | bit);
        }
        bytes[i] = value;
        if (ok)
            ok = transfer_bit(i + 1 == length, NULL); /* ACK all but the last byte. */
    }
    if (!stop())
        ok = false;
    return ok;
}

static bool clear_report(void)
{
    /* Companion write bank, register 7 command 2, as in V46 ARM +0xff02. */
    bool ok = start() && send_byte(0xae) && send_byte(7) && send_byte(2);
    if (!stop())
        ok = false;
    return ok;
}


void board_start(void)
{
    line(GPIO_BIT_0, true);
    line(GPIO_BIT_1, true);
    system_set_port_mux(GPIO_PORT_C, GPIO_BIT_0, PORTC0_FUNC_C0);
    system_set_port_mux(GPIO_PORT_C, GPIO_BIT_1, PORTC1_FUNC_C1);
    system_reset_dsp_set(); /* The standalone ARM app owns the shared display pins. */
    init_lcd();
    board_redraw();
    gpio_set_pin_value(GPIO_PORT_A, GPIO_BIT_7, 1);
}
/* Read current physical switches even when no interrupt flag is pending. */
bool board_sample(uint32_t *mask, uint8_t *wheel)
{
    uint8_t raw[4];
    if (!read_register(7, raw, sizeof(raw)) || !read_register(6, wheel, 1)) return false;
    *mask = (uint32_t)raw[0] | (uint32_t)raw[1]<<8 | (uint32_t)raw[2]<<16 | (uint32_t)raw[3]<<24;
    uint8_t flags;
    if (!read_register(0x0b, &flags, 1)) return false;
    return !flags || clear_report();
}
