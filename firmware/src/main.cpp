#include <Arduino.h>
#include <Adafruit_LSM6DSOX.h>

#define RGB_LED_PIN 38

// SPI2 pins and chip select for the LSM6DSOX
#define IMU_CS    10
#define SPI_SCK   12
#define SPI_MOSI  11  // SDX on the breakout board
#define SPI_MISO  13  // DO on the breakout board

Adafruit_LSM6DSOX imu;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide IMU bringup");

  // Green while trying to init
  neopixelWrite(RGB_LED_PIN, 0, 20, 0);

  if (!imu.begin_SPI(IMU_CS, SPI_SCK, SPI_MISO, SPI_MOSI)) {
    Serial.println("ERROR: LSM6DSOX not found. Check wiring and SPI jumper on breakout.");
    neopixelWrite(RGB_LED_PIN, 80, 0, 0);  // Red = failed
    while (1) { delay(100); }
  }

  Serial.println("LSM6DSOX found!");
  neopixelWrite(RGB_LED_PIN, 0, 0, 20);  // Blue = running

  // ±16g accel and ±2000 dps gyro per roadmap spec
  imu.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
  imu.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);

  // 104 Hz polling for now — FIFO + interrupt comes in Week 1
  imu.setAccelDataRate(LSM6DS_RATE_104_HZ);
  imu.setGyroDataRate(LSM6DS_RATE_104_HZ);

  Serial.println("IMU configured. Streaming accel (m/s^2) and gyro (rad/s)...");
  Serial.println("ax\tay\taz\tgx\tgy\tgz");
}

void loop() {
  sensors_event_t accel, gyro, temp;
  imu.getEvent(&accel, &gyro, &temp);

  // Tab-separated so Arduino Serial Plotter graphs all 6 axes live
  Serial.print(accel.acceleration.x); Serial.print("\t");
  Serial.print(accel.acceleration.y); Serial.print("\t");
  Serial.print(accel.acceleration.z); Serial.print("\t");
  Serial.print(gyro.gyro.x);         Serial.print("\t");
  Serial.print(gyro.gyro.y);         Serial.print("\t");
  Serial.println(gyro.gyro.z);

  delay(10);  // ~100 Hz print rate
}