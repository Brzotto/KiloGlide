#include <Arduino.h>
#include <Adafruit_LSM6DSOX.h>
#include <Adafruit_BusIO_Register.h>

#define RGB_LED_PIN 38

// SPI2 pins and chip select for the LSM6DSOX
#define IMU_CS    10
#define SPI_SCK   12
#define SPI_MOSI  11  // SDX on the breakout board
#define SPI_MISO  13  // DO on the breakout board

// LSM6DSOX register map — only the FIFO-related registers we drive directly.
// The Adafruit library handles ODR / range; it doesn't expose FIFO control,
// so we talk to these by hand.
constexpr uint8_t REG_FIFO_CTRL1   = 0x07;  // WTM[7:0]
constexpr uint8_t REG_FIFO_CTRL2   = 0x08;  // WTM[8] lives in bit 0
constexpr uint8_t REG_FIFO_CTRL3   = 0x09;  // BDR_GY[7:4] | BDR_XL[3:0]
constexpr uint8_t REG_FIFO_CTRL4   = 0x0A;  // FIFO_MODE[2:0]
constexpr uint8_t REG_FIFO_STATUS1 = 0x3A;  // DIFF_FIFO[7:0]   (samples queued)
constexpr uint8_t REG_FIFO_STATUS2 = 0x3B;  // bit7=WTM_IA, bits[1:0]=DIFF_FIFO[9:8]
constexpr uint8_t REG_FIFO_DATA    = 0x78;  // tag + 6 data bytes, auto-increments

// Tag values live in the top 5 bits of the tag byte. Many more tags exist
// (timestamp, temperature, config-change markers); we only consume these two.
constexpr uint8_t TAG_GYRO  = 0x01;
constexpr uint8_t TAG_ACCEL = 0x02;

// Watermark = how many samples queue up before the chip flags "drain me."
// Both accel and gyro batch independently, so a level of 32 means roughly
// 16 accel + 16 gyro samples accumulated — a comfortable working size.
constexpr uint16_t FIFO_WATERMARK = 32;

// Sensitivity constants from the LSM6DSOX datasheet (Table 2).
// The FIFO delivers raw int16 — multiply to get physical units.
// ±16g range:      0.488 mg/LSB → m/s²/LSB
// ±2000 dps range: 70 mdps/LSB  → rad/s/LSB
constexpr float ACCEL_SCALE = 0.000488f * 9.80665f;
constexpr float GYRO_SCALE  = 0.070f * (3.14159265f / 180.0f) / 1000.0f;

// The Adafruit library keeps `spi_dev` as a protected member. Subclassing
// lets us reuse the same SPI device the library already configured, instead
// of opening a second SPI session that would fight for the bus.
class IMU : public Adafruit_LSM6DSOX {
public:
  uint8_t readReg(uint8_t reg) {
    Adafruit_BusIO_Register r(spi_dev, reg, ADDRBIT8_HIGH_TOREAD);
    return r.read();
  }
  void writeReg(uint8_t reg, uint8_t val) {
    Adafruit_BusIO_Register r(spi_dev, reg, ADDRBIT8_HIGH_TOREAD);
    r.write(val);
  }
  // readBurst bypasses Adafruit_BusIO_Register whose read() takes uint8_t len
  // (max 255 bytes). At 64 entries × 7 bytes = 448, that silently truncates.
  // Going directly to spi_dev uses size_t so there's no limit.
  bool readBurst(uint8_t reg, uint8_t* buf, size_t n) {
    uint8_t addr = reg | 0x80;  // SPI read = address with bit 7 set
    return spi_dev->write_then_read(&addr, 1, buf, n);
  }
};

IMU imu;

static void configureFifo() {
  // Watermark threshold (9 bits split across CTRL1 + CTRL2 bit 0).
  imu.writeReg(REG_FIFO_CTRL1, FIFO_WATERMARK & 0xFF);
  imu.writeReg(REG_FIFO_CTRL2, 0x00);

  // Batch data rate. Encoding from the datasheet's BDR table:
  //   0001=12.5Hz  0010=26Hz  0011=52Hz  0100=104Hz  0110=416Hz
  // 0x44 = 0100_0100 — 104 Hz for both gyro (high nibble) and accel (low).
  // Match this to whatever ODR you set on the sensors below.
  imu.writeReg(REG_FIFO_CTRL3, 0x44);

  // FIFO mode bits[2:0]: 110 = continuous. If we ever fall behind, the chip
  // overwrites the oldest sample rather than stalling. We'd rather drop
  // stale data than block the sensor pipeline.
  imu.writeReg(REG_FIFO_CTRL4, 0x06);
}

static uint16_t fifoLevel() {
  uint8_t s1 = imu.readReg(REG_FIFO_STATUS1);
  uint8_t s2 = imu.readReg(REG_FIFO_STATUS2);
  return ((uint16_t)(s2 & 0x03) << 8) | s1;
}

// Drain everything currently in the FIFO. Each entry is 7 bytes:
//   [tag] [x_lo x_hi] [y_lo y_hi] [z_lo z_hi]
// The tag byte tells us whether this entry is accel, gyro, or something else.
static uint16_t drainFifo() {
  uint16_t available = fifoLevel();
  if (available == 0) return 0;

  // Cap each drain so a single SPI transaction stays bounded. If more is
  // queued, the next loop iteration sweeps it up — nothing is lost because
  // the chip keeps batching while we're busy.
  constexpr uint16_t kMaxDrain = 64;
  static uint8_t buf[kMaxDrain * 7];
  uint16_t toRead = available > kMaxDrain ? kMaxDrain : available;
  imu.readBurst(REG_FIFO_DATA, buf, (size_t)toRead * 7);

  // Walk every entry, keeping the most recent of each type.
  int16_t ax = 0, ay = 0, az = 0;
  int16_t gx = 0, gy = 0, gz = 0;
  for (uint16_t i = 0; i < toRead; i++) {
    uint8_t* s = &buf[i * 7];
    uint8_t tag = (s[0] >> 3) & 0x1F;
    int16_t x = (int16_t)(s[1] | ((uint16_t)s[2] << 8));
    int16_t y = (int16_t)(s[3] | ((uint16_t)s[4] << 8));
    int16_t z = (int16_t)(s[5] | ((uint16_t)s[6] << 8));
    if      (tag == TAG_ACCEL) { ax = x; ay = y; az = z; }
    else if (tag == TAG_GYRO)  { gx = x; gy = y; gz = z; }
  }

  // Scale raw int16 → physical units (m/s² and rad/s).
  // First column is drained count — watch it grow when the loop delay is high.
  Serial.print(toRead); Serial.print('\t');
  Serial.print(ax * ACCEL_SCALE, 3); Serial.print('\t');
  Serial.print(ay * ACCEL_SCALE, 3); Serial.print('\t');
  Serial.print(az * ACCEL_SCALE, 3); Serial.print('\t');
  Serial.print(gx * GYRO_SCALE,  4); Serial.print('\t');
  Serial.print(gy * GYRO_SCALE,  4); Serial.print('\t');
  Serial.println(gz * GYRO_SCALE, 4);
  return toRead;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("KiloGlide IMU bringup (FIFO polled)");

  neopixelWrite(RGB_LED_PIN, 0, 20, 0);

  if (!imu.begin_SPI(IMU_CS, SPI_SCK, SPI_MISO, SPI_MOSI)) {
    Serial.println("ERROR: LSM6DSOX not found. Check wiring and SPI jumper on breakout.");
    neopixelWrite(RGB_LED_PIN, 80, 0, 0);
    while (1) { delay(100); }
  }
  Serial.println("LSM6DSOX found");
  neopixelWrite(RGB_LED_PIN, 0, 0, 20);

  imu.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
  imu.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
  imu.setAccelDataRate(LSM6DS_RATE_104_HZ);
  imu.setGyroDataRate(LSM6DS_RATE_104_HZ);

  configureFifo();
  Serial.println("FIFO configured. Columns: drained  ax ay az (m/s2)  gx gy gz (rad/s)");
}

void loop() {
  drainFifo();
  // Deliberately slow. At 104 Hz, accel + gyro produce ~20 samples per 100 ms.
  // If the printed `drained` column hovers around 20, the chip is buffering
  // exactly as expected — samples accumulated in hardware while we slept.
  // Drop this delay to 0 later; it's here now only as a teaching signal.
  delay(100);
}
