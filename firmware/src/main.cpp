#include <Arduino.h>

#define RGB_LED_PIN 38

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("KiloGlide RGB blinky starting on GPIO 38");
}

void loop() {
  Serial.println("RED");
  neopixelWrite(RGB_LED_PIN, 255, 0, 0);
  delay(1000);

  Serial.println("GREEN");
  neopixelWrite(RGB_LED_PIN, 0, 255, 0);
  delay(1000);

  Serial.println("BLUE");
  neopixelWrite(RGB_LED_PIN, 0, 0, 255);
  delay(1000);

  Serial.println("OFF");
  neopixelWrite(RGB_LED_PIN, 0, 0, 0);
  delay(1000);
}