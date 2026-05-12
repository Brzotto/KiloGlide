// imu.cpp — LSM6DSOX driver implementation.
//
// All hardware-specific code lives here: SPI setup, register addresses, FIFO
// configuration, the watermark ISR. The rest of the firmware only sees the
// clean interface in imu.h.

#include "imu.h"

#include <Arduino.h>
#include <Adafruit_LSM6DSOX.h>
#include <Adafruit_BusIO_Register.h>

namespace {

// SPI2 pins and chip select for the LSM6DSOX
constexpr uint8_t IMU_CS   = 10;
constexpr uint8_t SPI_SCK  = 12;
constexpr uint8_t SPI_MOSI = 11;
constexpr uint8_t SPI_MISO = 13;

// INT1 from the LSM6DSOX → GPIO 4. The chip drives this pin high whenever
// the FIFO crosses our watermark threshold; the ESP32 sees that edge and
// fires an ISR that flags the loop to drain.
constexpr uint8_t IMU_INT1 = 4;

// LSM6DSOX register map — only the FIFO-related registers we drive directly.
// The Adafruit library handles ODR / range; it doesn't expose FIFO control,
// so we talk to these by hand.
constexpr uint8_t REG_INT1_CTRL    = 0x0D;
constexpr uint8_t REG_FIFO_CTRL1   = 0x07;
constexpr uint8_t REG_FIFO_CTRL2   = 0x08;
constexpr uint8_t REG_FIFO_CTRL3   = 0x09;
constexpr uint8_t REG_FIFO_CTRL4   = 0x0A;
constexpr uint8_t REG_FIFO_STATUS1 = 0x3A;
constexpr uint8_t REG_FIFO_STATUS2 = 0x3B;
constexpr uint8_t REG_FIFO_DATA    = 0x78;

constexpr uint8_t TAG_GYRO  = 0x01;
constexpr uint8_t TAG_ACCEL = 0x02;

constexpr uint16_t FIFO_WATERMARK = 32;

// Sensitivity constants from the LSM6DSOX datasheet (Table 2).
// ±16g range:      0.488 mg/LSB → m/s²/LSB
// ±2000 dps range: 70 mdps/LSB  → rad/s/LSB
constexpr float ACCEL_SCALE = 0.000488f * 9.80665f;
constexpr float GYRO_SCALE  = 0.070f * (3.14159265f / 180.0f);

// The Adafruit library keeps `spi_dev` as a protected member. Subclassing
// lets us reuse the same SPI device the library already configured, instead
// of opening a second SPI session that would fight for the bus.
class Imu : public Adafruit_LSM6DSOX {
public:
  uint8_t readReg(uint8_t reg) {
    Adafruit_BusIO_Register r(spi_dev, reg, ADDRBIT8_HIGH_TOREAD);
    return r.read();
  }
  void writeReg(uint8_t reg, uint8_t val) {
    Adafruit_BusIO_Register r(spi_dev, reg, ADDRBIT8_HIGH_TOREAD);
    r.write(val);
  }
  bool readBurst(uint8_t reg, uint8_t* buf, size_t n) {
    uint8_t addr = reg | 0x80;  // SPI read = address with bit 7 set
    return spi_dev->write_then_read(&addr, 1, buf, n);
  }
};

Imu dev;

// `volatile` tells the compiler "this variable can change behind your back" —
// without it, the optimizer might cache fifoReady in a register and never see
// the ISR's update.
volatile bool fifoReady = false;

// Most-recent values, exposed through the getters in imu.h.
float g_ax = 0, g_ay = 0, g_az = 0;
float g_gx = 0, g_gy = 0, g_gz = 0;

// The ISR. Mark with IRAM_ATTR so it runs from instruction RAM (flash can be
// unavailable mid-write). Keep it short — just flip a flag and return.
void IRAM_ATTR onFifoWatermark() {
  fifoReady = true;
}

void configureFifo() {
  // Watermark threshold (9 bits split across CTRL1 + CTRL2 bit 0).
  dev.writeReg(REG_FIFO_CTRL1, FIFO_WATERMARK & 0xFF);
  dev.writeReg(REG_FIFO_CTRL2, 0x00);

  // Batch data rate. 0x44 = 0100_0100 = 104 Hz for both gyro and accel.
  // Match this to whatever ODR is set on the sensors.
  dev.writeReg(REG_FIFO_CTRL3, 0x44);

  // FIFO mode bits[2:0]: 110 = continuous. Oldest sample gets overwritten if
  // we ever fall behind — we'd rather drop stale data than block the pipeline.
  dev.writeReg(REG_FIFO_CTRL4, 0x06);
}

uint16_t fifoLevel() {
  uint8_t s1 = dev.readReg(REG_FIFO_STATUS1);
  uint8_t s2 = dev.readReg(REG_FIFO_STATUS2);
  return ((uint16_t)(s2 & 0x03) << 8) | s1;
}

// Drain everything currently in the FIFO. Each entry is 7 bytes:
//   [tag] [x_lo x_hi] [y_lo y_hi] [z_lo z_hi]
// Updates the most-recent globals as a side effect. Returns sample count.
uint16_t drainFifo() {
  uint16_t available = fifoLevel();
  if (available == 0) return 0;

  // Cap each drain so a single SPI transaction stays bounded. If more is
  // queued, the next loop iteration sweeps it up.
  constexpr uint16_t kMaxDrain = 64;
  static uint8_t buf[kMaxDrain * 7];
  uint16_t toRead = available > kMaxDrain ? kMaxDrain : available;
  dev.readBurst(REG_FIFO_DATA, buf, (size_t)toRead * 7);

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

  g_ax = ax * ACCEL_SCALE;
  g_ay = ay * ACCEL_SCALE;
  g_az = az * ACCEL_SCALE;
  g_gx = gx * GYRO_SCALE;
  g_gy = gy * GYRO_SCALE;
  g_gz = gz * GYRO_SCALE;
  return toRead;
}

}  // namespace

namespace imu {

bool init() {
  if (!dev.begin_SPI(IMU_CS, SPI_SCK, SPI_MISO, SPI_MOSI)) {
    return false;
  }

  dev.setAccelRange(LSM6DS_ACCEL_RANGE_16_G);
  dev.setGyroRange(LSM6DS_GYRO_RANGE_2000_DPS);
  dev.setAccelDataRate(LSM6DS_RATE_104_HZ);
  dev.setGyroDataRate(LSM6DS_RATE_104_HZ);

  configureFifo();

  // Bit 3 of INT1_CTRL is INT1_FIFO_TH. Default polarity is active-high,
  // push-pull — no need to touch CTRL3_C.
  dev.writeReg(REG_INT1_CTRL, 0x08);

  pinMode(IMU_INT1, INPUT);
  attachInterrupt(digitalPinToInterrupt(IMU_INT1), onFifoWatermark, RISING);
  return true;
}

bool update() {
  if (!fifoReady) return false;
  // Clear the flag BEFORE we drain. If a new watermark fires while we're
  // mid-drain, the ISR re-sets the flag and we'll catch it next iteration.
  fifoReady = false;

  bool gotSample = false;
  while (drainFifo() > 0) { gotSample = true; }
  return gotSample;
}

float ax() { return g_ax; }
float ay() { return g_ay; }
float az() { return g_az; }
float gx() { return g_gx; }
float gy() { return g_gy; }
float gz() { return g_gz; }

}  // namespace imu
