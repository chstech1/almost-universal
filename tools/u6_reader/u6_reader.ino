#include <SPI.h>
#include <cstring>

constexpr uint8_t chipSelectPin = D2;
constexpr uint32_t flashSize = 16 * 1024 * 1024;
constexpr uint32_t sectionSize = 1024 * 1024;
constexpr size_t burstSize = 64;
constexpr uint32_t verificationLead = 16;
constexpr uint32_t chipId = 0x5E4018;
constexpr uint8_t readIdCommand = 0x9F;
constexpr uint8_t readDataCommand = 0x03;
const SPISettings fastIdSettings(500000, MSBFIRST, SPI_MODE0);
const SPISettings slowReadSettings(100000, MSBFIRST, SPI_MODE0);
alignas(4) uint8_t buffer[4096];

void selectFlash(const SPISettings& settings) {
  digitalWrite(chipSelectPin, HIGH);
  pinMode(chipSelectPin, OUTPUT);
  SPI.begin();
  SPI.beginTransaction(settings);
  digitalWrite(chipSelectPin, LOW);
  delayMicroseconds(2);
}

void releaseFlash() {
  digitalWrite(chipSelectPin, HIGH);
  delayMicroseconds(2);
  SPI.endTransaction();
  SPI.end();
  pinMode(chipSelectPin, INPUT);
}

uint32_t readChipId(const SPISettings& settings) {
  selectFlash(settings);
  SPI.transfer(readIdCommand);
  const uint32_t manufacturer = SPI.transfer(0);
  const uint32_t type = SPI.transfer(0);
  const uint32_t capacity = SPI.transfer(0);
  releaseFlash();
  return (manufacturer << 16) | (type << 8) | capacity;
}

void readFlash(uint32_t address, uint8_t* data, size_t length, const SPISettings& settings) {
  selectFlash(settings);
  SPI.transfer(readDataCommand);
  SPI.transfer(static_cast<uint8_t>(address >> 16));
  SPI.transfer(static_cast<uint8_t>(address >> 8));
  SPI.transfer(static_cast<uint8_t>(address));
  SPI.transferBytes(nullptr, data, length);
  releaseFlash();
}

bool readVerifiedBurst(uint32_t address, uint8_t* data, const SPISettings& settings) {
  alignas(4) uint8_t verification[burstSize + verificationLead];
  const uint32_t lead = address < verificationLead ? address : verificationLead;
  for (int attempt = 0; attempt < 5; ++attempt) {
    readFlash(address, data, burstSize, settings);
    // Start the second transaction earlier so an extra clock must affect two alignments identically.
    readFlash(address - lead, verification, burstSize + lead, settings);
    if (std::memcmp(data, verification + lead, burstSize) == 0) {
      return true;
    }
  }
  return false;
}

void setup() {
  pinMode(chipSelectPin, INPUT);
  Serial.begin(460800);
  Serial.setTimeout(500);
  Serial.println("U6 reader ready");
}

void loop() {
  const int command = Serial.read();
  const bool sample = command == 'b' || command == 'c';
  if (command != 'i' && command != 's' && !sample && command != 'r' && command != 'p') {
    delay(1);
    return;
  }

  // The diagnostic range covers blocks where the 100 kHz section still lost bits.
  uint32_t startAddress = command == 'c' ? 0x17000 : 0;
  uint32_t length = command == 'c' ? 16 * 1024 : (sample ? sizeof(buffer) : flashSize);
  if (command == 'p') {
    // A section request supplies one binary section number (0 through 15).
    uint8_t section;
    if (Serial.readBytes(&section, 1) != 1 || section >= flashSize / sectionSize) {
      Serial.println("ERR section");
      return;
    }
    startAddress = section * sectionSize;
    length = sectionSize;
  }

  const SPISettings& settings = command == 'i' ? fastIdSettings : slowReadSettings;
  const uint32_t observedId = readChipId(settings);
  Serial.printf("ID %06lX\n", static_cast<unsigned long>(observedId));
  if ((command == 'i' || command == 's') || observedId != chipId) {
    return;
  }

  Serial.printf("DUMP %lu\n", static_cast<unsigned long>(length));
  for (uint32_t offset = 0; offset < length; offset += sizeof(buffer)) {
    for (size_t position = 0; position < sizeof(buffer); position += burstSize) {
      if (!readVerifiedBurst(startAddress + offset + position, buffer + position, settings)) {
        return;
      }
      yield();
    }
    Serial.write(buffer, sizeof(buffer));
  }
  Serial.flush();
}
