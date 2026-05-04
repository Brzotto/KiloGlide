#include <Arduino.h>

// ESP32-S3-DevKitC-1 onboard RGB LED on GPIO 48
#define LED_PIN 48

void setup() {
    Serial.begin(115200);
    delay(2000);  // Give USB-CDC time to enumerate
    Serial.println("KiloGlide firmware booting...");

    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("blink");
    delay(500);
    digitalWrite(LED_PIN, LOW);
    delay(500);
}
