#include <Arduino.h>
#include <Wire.h>
#include <SparkFun_u-blox_GNSS_v3.h>

#define RGB_LED_PIN 38

// I2C pins for the SAM-M8Q (Qwiic breakout)
#define GPS_SDA 8
#define GPS_SCL 9

SFE_UBLOX_GNSS gps;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide GPS bringup");

  neopixelWrite(RGB_LED_PIN, 0, 20, 0);  // green = booting

  Wire.begin(GPS_SDA, GPS_SCL);

  if (!gps.begin(Wire)) {
    Serial.println("ERROR: SAM-M8Q not found. Check Qwiic wiring.");
    neopixelWrite(RGB_LED_PIN, 80, 0, 0);  // red = error
    while (1) { delay(100); }
  }
  Serial.println("SAM-M8Q found");

  // UBX binary protocol — faster and more reliable than NMEA parsing.
  // Disable NMEA so we don't waste I2C bandwidth on sentences we ignore.
  gps.setI2COutput(COM_TYPE_UBX);

  // 1 Hz is the default; fine for bringup. We'll bump to 5 Hz in Wave 2.
  gps.setNavigationFrequency(1);

  // Save the config to battery-backed RAM so it survives a power cycle.
  // Not strictly needed for a test, but good practice.
  gps.saveConfigSelective(VAL_CFG_SUBSEC_IOPORT);

  neopixelWrite(RGB_LED_PIN, 0, 0, 20);  // blue = running
  Serial.println("Waiting for fix... (30-90 sec cold start, needs sky view)");
  Serial.println("fix\tsats\tlat\t\tlon\t\talt(m)\tspeed(m/s)");
}

void loop() {
  // getPVT() polls the module for Position/Velocity/Time.
  // Returns true when fresh data is available.
  if (gps.getPVT()) {
    uint8_t fix = gps.getFixType();
    uint8_t sats = gps.getSIV();

    // Lat/lon come back as degrees * 1e-7 (int32). Divide to get degrees.
    double lat = gps.getLatitude() / 1e7;
    double lon = gps.getLongitude() / 1e7;
    double alt = gps.getAltitudeMSL() / 1000.0;  // mm → m
    double speed = gps.getGroundSpeed() / 1000.0; // mm/s → m/s

    // Fix types: 0=none, 1=dead reckoning, 2=2D, 3=3D, 4=GNSS+DR, 5=time only
    Serial.print(fix);    Serial.print('\t');
    Serial.print(sats);   Serial.print('\t');
    Serial.print(lat, 7); Serial.print('\t');
    Serial.print(lon, 7); Serial.print('\t');
    Serial.print(alt, 1); Serial.print('\t');
    Serial.println(speed, 2);

    // LED feedback: green = 3D fix, yellow = 2D or acquiring, red = no sats
    if (fix >= 3)      neopixelWrite(RGB_LED_PIN, 0, 20, 0);
    else if (sats > 0) neopixelWrite(RGB_LED_PIN, 20, 20, 0);
    else               neopixelWrite(RGB_LED_PIN, 20, 0, 0);
  }

  delay(100);
}
