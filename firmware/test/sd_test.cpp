// sd_test.cpp — Standalone bringup test for the Adafruit microSD breakout.
//
// Verifies SPI3 wiring, card detection, and FAT filesystem access. Writes a
// test file, reads it back, and prints results. Doesn't touch IMU or GPS —
// pure SD bringup so any failure is unambiguous.

#include <Arduino.h>
#include <SPI.h>
#include <SdFat.h>

#define RGB_LED_PIN 38

// SPI3 pins for the Adafruit microSD breakout. SPI3 is dedicated to the SD
// card — sharing the SPI2 bus with the IMU causes weird intermittent failures.
constexpr uint8_t SD_CS   = 5;
constexpr uint8_t SD_SCK  = 6;
constexpr uint8_t SD_MOSI = 7;
constexpr uint8_t SD_MISO = 14;

// On ESP32-S3, HSPI maps to the third SPI peripheral (SPI3). FSPI is the
// second (SPI2, already used by the IMU). Creating our own SPIClass instance
// lets us hand SdFat a bus that's completely separate from the IMU.
SPIClass sdSPI(HSPI);

// 20 MHz is a safe starting point for SPI to most cards. Some cards push 40+,
// but breadboard wiring won't reliably support that — wait until we're on PCB.
SdFat sd;
SdSpiConfig sdConfig(SD_CS, DEDICATED_SPI, SD_SCK_MHZ(20), &sdSPI);

void halt(const char* msg) {
  Serial.print("ERROR: ");
  Serial.println(msg);
  neopixelWrite(RGB_LED_PIN, 80, 0, 0);  // red = stop
  while (1) { delay(100); }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide SD bringup");

  neopixelWrite(RGB_LED_PIN, 0, 20, 0);  // green = booting

  // Start SPI3 with the pins we picked. The fourth arg (SS) is unused since
  // SdFat manages the chip-select itself.
  sdSPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

  Serial.println("Mounting SD card...");
  if (!sd.begin(sdConfig)) {
    sd.initErrorPrint(&Serial);
    halt("sd.begin() failed");
  }
  Serial.println("Mounted.");

  // Card info — useful sanity check that we're actually talking to the card
  // we think we are.
  uint32_t sizeMB = sd.card()->sectorCount() / 2048;  // 512-byte sectors → MB
  Serial.print("Card size: "); Serial.print(sizeMB); Serial.println(" MB");
  Serial.print("FAT type:  "); Serial.println(sd.vol()->fatType());

  // List existing files at the root, just to confirm the FS is readable.
  Serial.println("Root directory:");
  FsFile root;
  if (root.open("/")) {
    FsFile entry;
    while (entry.openNext(&root)) {
      Serial.print("  ");
      char name[64];
      entry.getName(name, sizeof(name));
      Serial.print(name);
      Serial.print("  ");
      Serial.print(entry.fileSize());
      Serial.println(" bytes");
      entry.close();
    }
    root.close();
  }

  // --- Write test ---
  Serial.println("Writing test.txt...");
  FsFile f;
  if (!f.open("test.txt", O_WRONLY | O_CREAT | O_TRUNC)) {
    halt("open(test.txt) for write failed");
  }
  for (int i = 0; i < 10; i++) {
    f.print("line ");
    f.println(i);
  }
  f.close();
  Serial.println("Wrote 10 lines.");

  // --- Read-back test ---
  Serial.println("Reading test.txt back:");
  if (!f.open("test.txt", O_RDONLY)) {
    halt("open(test.txt) for read failed");
  }
  while (f.available()) {
    Serial.write(f.read());
  }
  f.close();

  Serial.println("---");
  Serial.println("SD test complete. Card is healthy.");
  neopixelWrite(RGB_LED_PIN, 0, 20, 0);  // green = success
}

void loop() {
  // Heartbeat blink so we know the firmware didn't crash silently.
  neopixelWrite(RGB_LED_PIN, 0, 20, 0);
  delay(500);
  neopixelWrite(RGB_LED_PIN, 0, 0, 0);
  delay(500);
}
