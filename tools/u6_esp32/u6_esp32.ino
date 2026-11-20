#include <SPI.h>
#include <cstring>
#include <driver/gpio.h>
#include <driver/pulse_cnt.h>
#include <driver/uart.h>
#include <esp_rom_crc.h>
#include <esp_timer.h>

constexpr gpio_num_t chipSelectPin = GPIO_NUM_27;
constexpr int clockPin = 18;
constexpr int inputPin = 19;
constexpr int outputPin = 23;
constexpr int dspReceivePin = 16;
constexpr uart_port_t dspUart = UART_NUM_2;
constexpr uint32_t flashSize = 16 * 1024 * 1024;
constexpr uint32_t sectionSize = 1024 * 1024;
constexpr uint32_t diagnosticAddress = 0x6000;
constexpr size_t maxBurstSize = 256;
constexpr size_t verificationLead = 16;
constexpr uint32_t chipId = 0x5E4018;
constexpr uint8_t readIdCommand = 0x9F;
constexpr uint8_t readDataCommand = 0x03;
alignas(4) uint8_t buffer[4096];

struct ReaderSettings {
  uint32_t spiHz = 100000;
  uint32_t spiMode = 0;
  uint32_t burstSize = 64;
  uint32_t readAttempts = 5;
  uint32_t dspBaud = 115200;
  uint32_t ackTimeoutMs = 1000;
  uint32_t usbAttempts = 6;
} settings;

// Each line header is immediately followed by exactly length raw bytes.
void sendFrame(const char* kind, uint32_t value, const uint8_t* data = nullptr, size_t length = 0) {
  const uint32_t crc = length ? esp_rom_crc32_le(0, data, length) : 0;
  Serial.printf("@U6 %s %llu %lu %u %08lx\n", kind,
                static_cast<unsigned long long>(esp_timer_get_time()),
                static_cast<unsigned long>(value), static_cast<unsigned>(length),
                static_cast<unsigned long>(crc));
  if (length) {
    Serial.write(data, length);
  }
}

bool initDspReceiver() {
  const uart_config_t config = {
      .baud_rate = static_cast<int>(settings.dspBaud),
      .data_bits = UART_DATA_8_BITS,
      .parity = UART_PARITY_DISABLE,
      .stop_bits = UART_STOP_BITS_1,
      .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
      .source_clk = UART_SCLK_DEFAULT,
  };
  return uart_driver_install(dspUart, 8192, 0, 0, nullptr, 0) == ESP_OK &&
         uart_param_config(dspUart, &config) == ESP_OK &&
         uart_set_pin(dspUart, UART_PIN_NO_CHANGE, dspReceivePin,
                      UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) == ESP_OK;
}

bool dspReady;

void reportSettings() {
  char json[256];
  const int length = snprintf(
      json, sizeof(json),
      "{\"spi_hz\":%lu,\"spi_mode\":%lu,\"burst_bytes\":%lu,\"read_attempts\":%lu,"
      "\"dsp_baud\":%lu,\"ack_timeout_ms\":%lu,\"usb_attempts\":%lu}",
      static_cast<unsigned long>(settings.spiHz), static_cast<unsigned long>(settings.spiMode),
      static_cast<unsigned long>(settings.burstSize), static_cast<unsigned long>(settings.readAttempts),
      static_cast<unsigned long>(settings.dspBaud), static_cast<unsigned long>(settings.ackTimeoutMs),
      static_cast<unsigned long>(settings.usbAttempts));
  sendFrame("SETTINGS", 0, reinterpret_cast<const uint8_t*>(json), length);
}

uint32_t readLittleEndian(const uint8_t* bytes) {
  return uint32_t(bytes[0]) | (uint32_t(bytes[1]) << 8) |
         (uint32_t(bytes[2]) << 16) | (uint32_t(bytes[3]) << 24);
}

bool updateSetting(uint8_t field, uint32_t value) {
  switch (field) {
    case 'f':
      if (value < 50000 || value > 1000000) return false;
      settings.spiHz = value;
      return true;
    case 'm':
      if (value != 0 && value != 3) return false;
      settings.spiMode = value;
      return true;
    case 'b':
      if (value < 16 || value > maxBurstSize || (value & (value - 1))) return false;
      settings.burstSize = value;
      return true;
    case 'r':
      if (value < 1 || value > 5) return false;
      settings.readAttempts = value;
      return true;
    case 'd':
      if (!dspReady || value < 1200 || value > 230400 ||
          uart_set_baudrate(dspUart, value) != ESP_OK) return false;
      settings.dspBaud = value;
      return true;
    case 't':
      if (value < 250 || value > 5000) return false;
      settings.ackTimeoutMs = value;
      return true;
    case 'u':
      if (value < 1 || value > 10) return false;
      settings.usbAttempts = value;
      return true;
    default:
      return false;
  }
}

void drainDsp() {
  if (!dspReady) {
    return;
  }
  uint8_t bytes[256];
  const int count = uart_read_bytes(dspUart, bytes, sizeof(bytes), 0);
  if (count > 0) {
    sendFrame("LOG", 0, bytes, count);
  }
}

struct BusCounter {
  pcnt_unit_handle_t unit = nullptr;
  pcnt_channel_handle_t channel = nullptr;
  bool enabled = false;
  bool running = false;

  bool start(int edgePin, int gatePin, bool countRising) {
    pcnt_unit_config_t config = {};
    config.low_limit = -32768;
    config.high_limit = 32767;
    config.flags.accum_count = true;
    pcnt_chan_config_t pins = {};
    pins.edge_gpio_num = edgePin;
    pins.level_gpio_num = gatePin;
    const auto increase = PCNT_CHANNEL_EDGE_ACTION_INCREASE;
    const auto ignore = PCNT_CHANNEL_EDGE_ACTION_HOLD;
    if (pcnt_new_unit(&config, &unit) != ESP_OK ||
        pcnt_new_channel(unit, &pins, &channel) != ESP_OK ||
        pcnt_channel_set_edge_action(channel, countRising ? increase : ignore,
                                     countRising ? ignore : increase) != ESP_OK ||
        pcnt_unit_add_watch_point(unit, config.high_limit) != ESP_OK) {
      return false;
    }
    if (gatePin >= 0 &&
        pcnt_channel_set_level_action(channel, PCNT_CHANNEL_LEVEL_ACTION_HOLD,
                                      PCNT_CHANNEL_LEVEL_ACTION_KEEP) != ESP_OK) {
      return false;
    }
    enabled = pcnt_unit_enable(unit) == ESP_OK;
    running = enabled && pcnt_unit_clear_count(unit) == ESP_OK && pcnt_unit_start(unit) == ESP_OK;
    return running;
  }

  ~BusCounter() {
    if (running) pcnt_unit_stop(unit);
    if (enabled) pcnt_unit_disable(unit);
    if (channel) pcnt_del_channel(channel);
    if (unit) pcnt_del_unit(unit);
  }
};

void observeBus() {
  constexpr uint32_t intervalMs = 1000;
  constexpr uint32_t durationMs = 20000;
  BusCounter clock, select;
  // SPI is already detached. Count clock pulses only while U6 is selected.
  if (!clock.start(clockPin, chipSelectPin, true) || !select.start(chipSelectPin, -1, false) ||
      gpio_set_pull_mode(static_cast<gpio_num_t>(clockPin), GPIO_FLOATING) != ESP_OK ||
      gpio_set_pull_mode(chipSelectPin, GPIO_FLOATING) != ESP_OK ||
      pcnt_unit_clear_count(clock.unit) != ESP_OK || pcnt_unit_clear_count(select.unit) != ESP_OK) {
    sendFrame("MONITOR_ERROR", 0);
    return;
  }

  sendFrame("PASSIVE_START", durationMs);
  const uint32_t started = millis();
  uint32_t nextReport = intervalMs;
  int previousClock = 0, previousSelect = 0;
  while (nextReport <= durationMs) {
    drainDsp();
    if (Serial.read() == 'x') {
      sendFrame("ABORT", 0);
      return;
    }
    const uint32_t elapsed = millis() - started;
    if (elapsed >= nextReport) {
      int clocks, selections;
      if (pcnt_unit_get_count(clock.unit, &clocks) != ESP_OK ||
          pcnt_unit_get_count(select.unit, &selections) != ESP_OK) {
        sendFrame("MONITOR_ERROR", 0);
        return;
      }
      char json[96];
      const int length = snprintf(json, sizeof(json), "{\"clocks\":%d,\"selects\":%d,\"cs\":%d}",
                                  clocks - previousClock, selections - previousSelect,
                                  gpio_get_level(chipSelectPin));
      sendFrame("BUS", elapsed, reinterpret_cast<const uint8_t*>(json), length);
      previousClock = clocks;
      previousSelect = selections;
      nextReport += intervalMs;
    }
    delay(1);
  }
  sendFrame("PASSIVE_DONE", durationMs);
}

void selectFlash() {
  gpio_set_level(chipSelectPin, HIGH);
  pinMode(chipSelectPin, OUTPUT);
  SPI.begin(clockPin, inputPin, outputPin, -1);
  SPI.beginTransaction(SPISettings(settings.spiHz, MSBFIRST,
                                   settings.spiMode == 3 ? SPI_MODE3 : SPI_MODE0));
  digitalWrite(chipSelectPin, LOW);
  delayMicroseconds(2);
}

void releaseFlash() {
  digitalWrite(chipSelectPin, HIGH);
  delayMicroseconds(2);
  SPI.endTransaction();
  SPI.end();
  pinMode(chipSelectPin, INPUT);
  pinMode(clockPin, INPUT);
  pinMode(outputPin, INPUT);
  pinMode(inputPin, INPUT);
}

uint32_t readChipId() {
  selectFlash();
  SPI.transfer(readIdCommand);
  const uint32_t manufacturer = SPI.transfer(0);
  const uint32_t type = SPI.transfer(0);
  const uint32_t capacity = SPI.transfer(0);
  releaseFlash();
  return (manufacturer << 16) | (type << 8) | capacity;
}

void readFlash(uint32_t address, uint8_t* data, size_t length) {
  selectFlash();
  SPI.transfer(readDataCommand);
  SPI.transfer(static_cast<uint8_t>(address >> 16));
  SPI.transfer(static_cast<uint8_t>(address >> 8));
  SPI.transfer(static_cast<uint8_t>(address));
  SPI.transferBytes(nullptr, data, length);
  releaseFlash();
}

bool readVerifiedBurst(uint32_t address, uint8_t* data) {
  alignas(4) uint8_t verification[maxBurstSize + verificationLead];
  const size_t lead = address < verificationLead ? address : verificationLead;
  for (uint32_t attempt = 0; attempt < settings.readAttempts; ++attempt) {
    readFlash(address, data, settings.burstSize);
    readFlash(address - lead, verification, settings.burstSize + lead);
    drainDsp();
    if (std::memcmp(data, verification + lead, settings.burstSize) == 0) {
      return true;
    }
  }
  return false;
}

bool sendAcknowledgedBlock(uint32_t address) {
  const uint16_t block = address / sizeof(buffer);
  for (uint32_t attempt = 0; attempt < settings.usbAttempts; ++attempt) {
    sendFrame("DATA", address, buffer, sizeof(buffer));
    const uint32_t started = millis();
    while (millis() - started < settings.ackTimeoutMs) {
      drainDsp();
      const int reply = Serial.read();
      if (reply == 'x') {
        sendFrame("ABORT", address);
        return false;
      }
      if (reply == 'a') {
        uint8_t bytes[2];
        if (Serial.readBytes(bytes, sizeof(bytes)) == sizeof(bytes) &&
            (bytes[0] | (uint16_t(bytes[1]) << 8)) == block) {
          return true;
        }
      }
      delay(1);
    }
  }
  sendFrame("USB_ERROR", address);
  return false;
}

void setup() {
  pinMode(chipSelectPin, INPUT);
  pinMode(clockPin, INPUT);
  pinMode(inputPin, INPUT);
  pinMode(outputPin, INPUT);
  Serial.begin(460800);
  Serial.setTimeout(500);
  dspReady = initDspReceiver();
  sendFrame("READY", dspReady);
}

void loop() {
  drainDsp();
  const int command = Serial.read();
  if (command == '?' || command == 'x') {
    sendFrame(command == '?' ? "READY" : "ABORT", command == '?' ? dspReady : 0);
    return;
  }
  if (command == 'g') {
    reportSettings();
    return;
  }
  if (command == 'v') {
    observeBus();
    return;
  }
  if (command == 'k') {
    uint8_t request[5];
    if (Serial.readBytes(request, sizeof(request)) != sizeof(request) ||
        !updateSetting(request[0], readLittleEndian(request + 1))) {
      sendFrame("BAD_SETTING", 0);
    } else {
      reportSettings();
    }
    return;
  }
  if (command != 'i' && command != 'b' && command != 'c' && command != 'p' &&
      command != 'r' && command != 'q') {
    delay(1);
    return;
  }

  uint32_t start = command == 'c' ? diagnosticAddress : 0;
  uint32_t length = command == 'b' ? sizeof(buffer) : (command == 'c' ? 16 * 1024 : flashSize);
  if (command == 'p') {
    uint8_t section;
    if (Serial.readBytes(&section, 1) != 1 || section >= flashSize / sectionSize) {
      sendFrame("BAD_SECTION", 0);
      return;
    }
    start = section * sectionSize;
    length = sectionSize;
  }
  if (command == 'q') {
    uint8_t request[8];
    if (Serial.readBytes(request, sizeof(request)) != sizeof(request)) {
      sendFrame("BAD_RANGE", 0);
      return;
    }
    start = readLittleEndian(request);
    length = readLittleEndian(request + 4);
    if (start >= flashSize || !length || length > flashSize - start ||
        start % sizeof(buffer) || length % sizeof(buffer)) {
      sendFrame("BAD_RANGE", start);
      return;
    }
  }

  const uint32_t observedId = readChipId();
  drainDsp();
  sendFrame("ID", observedId);
  if (command == 'i' || observedId != chipId) {
    return;
  }

  sendFrame("START", start);
  const bool acknowledged = command == 'r' || command == 'p' || command == 'q';
  for (uint32_t offset = 0; offset < length; offset += sizeof(buffer)) {
    for (size_t position = 0; position < sizeof(buffer); position += settings.burstSize) {
      const uint32_t address = start + offset + position;
      if (Serial.peek() == 'x') {
        Serial.read();
        sendFrame("ABORT", address);
        return;
      }
      if (!readVerifiedBurst(address, buffer + position)) {
        drainDsp();
        sendFrame("READ_ERROR", address);
        return;
      }
      yield();
    }
    if (acknowledged) {
      if (!sendAcknowledgedBlock(start + offset)) {
        return;
      }
    } else {
      sendFrame("DATA", start + offset, buffer, sizeof(buffer));
    }
  }
  drainDsp();
  sendFrame("DONE", start + length);
}
