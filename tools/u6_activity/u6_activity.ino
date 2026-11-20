constexpr uint8_t chipSelectPin = 4;  // D2 on the NodeMCU ESP8266.
volatile uint32_t fallingEdges = 0;

void IRAM_ATTR countSelection() {
  ++fallingEdges;
}

void setup() {
  pinMode(chipSelectPin, INPUT);
  attachInterrupt(digitalPinToInterrupt(chipSelectPin), countSelection, FALLING);
  Serial.begin(115200);
  Serial.println("U6 activity listener ready on D2");
}

void loop() {
  static uint32_t previousCount = 0;
  delay(1000);

  const uint32_t count = fallingEdges;
  Serial.printf("D2=%s, falling edges in the last second: %lu\n",
                digitalRead(chipSelectPin) == HIGH ? "HIGH" : "LOW",
                static_cast<unsigned long>(count - previousCount));
  previousCount = count;
}
