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

// INT1 from the LSM6DSOX -> GPIO 4. The chip drives this pin high whenever
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

// FIFO watermark threshold.
// At 416 Hz with both accel + gyro batched, the FIFO receives 832 entries/sec.
// Watermark 208 fires the IRQ ~4 times/sec, leaving 304 slots of headroom
// (~365 ms) before the 512-deep FIFO would overflow. That's comfortable
// margin even if a drain gets delayed by an SD write spike.
// (Previous value was 32, which at 416 Hz would fire 26 times/sec — too much
// ISR + drain overhead.)
constexpr uint16_t FIFO_WATERMARK = 208;

// Maximum paired samples we can buffer from one complete FIFO drain.
// The FIFO holds 512 entries max. Each accel+gyro pair consumes 2 FIFO slots,
// so 256 pairs is the theoretical maximum.
constexpr uint16_t MAX_SAMPLES = 256;

// Maximum FIFO entries to read in a single SPI burst. Keeps each SPI
// transaction bounded. If more data is queued, the drain loop comes back
// for another pass.
constexpr uint16_t MAX_BURST_ENTRIES = 128;

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

// Sample buffer: filled by update(), read by callers via count()/samples().
imu::Sample sampleBuf[MAX_SAMPLES];
uint16_t    sampleCount = 0;

// The ISR. Mark with IRAM_ATTR so it runs from instruction RAM (flash can be
// unavailable mid-write). Keep it short — just flip a flag and return.
void IRAM_ATTR onFifoWatermark() {
  fifoReady = true;
}

void configureFifo() {
  // Watermark threshold (9 bits split across CTRL1[7:0] + CTRL2[0]).
  // 208 = 0x00D0 — fits in the lower 8 bits, bit 8 is 0.
  dev.writeReg(REG_FIFO_CTRL1, FIFO_WATERMARK & 0xFF);
  dev.writeReg(REG_FIFO_CTRL2, (FIFO_WATERMARK >> 8) & 0x01);

  // Batch data rate for both accel and gyro: 416 Hz.
  // REG_FIFO_CTRL3 bits [3:0] = accel BDR, bits [7:4] = gyro BDR.
  // 0110 = 416 Hz per the LSM6DSOX datasheet BDR table.
  // So 0x66 = both at 416 Hz.
  dev.writeReg(REG_FIFO_CTRL3, 0x66);

  // FIFO mode bits[2:0]: 110 = continuous. Oldest sample gets overwritten if
  // we ever fall behind — we'd rather drop stale data than block the pipeline.
  dev.writeReg(REG_FIFO_CTRL4, 0x06);
}

uint16_t fifoLevel() {
  uint8_t s1 = dev.readReg(REG_FIFO_STATUS1);
  uint8_t s2 = dev.readReg(REG_FIFO_STATUS2);
  return ((uint16_t)(s2 & 0x03) << 8) | s1;
}

// Read one burst from the FIFO and pair accel+gyro entries into Samples.
// Appends to sampleBuf starting at sampleCount. Returns how many FIFO
// entries were consumed (not how many Samples were created).
uint16_t drainBurst() {
  uint16_t available = fifoLevel();
  if (available == 0) return 0;

  uint16_t toRead = available > MAX_BURST_ENTRIES ? MAX_BURST_ENTRIES : available;

  // Raw FIFO data: each entry is 7 bytes [tag, x_lo, x_hi, y_lo, y_hi, z_lo, z_hi]
  static uint8_t buf[MAX_BURST_ENTRIES * 7];
  dev.readBurst(REG_FIFO_DATA, buf, (size_t)toRead * 7);

  // Temporaries for pairing. At equal BDR, accel and gyro entries alternate
  // in the FIFO. We accumulate each half and emit a Sample when we have both.
  int16_t ax = 0, ay = 0, az = 0;
  int16_t gx = 0, gy = 0, gz = 0;
  bool haveAccel = false;
  bool haveGyro  = false;

  for (uint16_t i = 0; i < toRead; i++) {
    uint8_t* e = &buf[i * 7];
    uint8_t tag = (e[0] >> 3) & 0x1F;
    int16_t x = (int16_t)(e[1] | ((uint16_t)e[2] << 8));
    int16_t y = (int16_t)(e[3] | ((uint16_t)e[4] << 8));
    int16_t z = (int16_t)(e[5] | ((uint16_t)e[6] << 8));

    if (tag == TAG_ACCEL) {
      ax = x; ay = y; az = z;
      haveAccel = true;
    } else if (tag == TAG_GYRO) {
      gx = x; gy = y; gz = z;
      haveGyro = true;
    }

    // Once we have both halves, emit a paired Sample.
    if (haveAccel && haveGyro) {
      if (sampleCount < MAX_SAMPLES) {
        sampleBuf[sampleCount] = { ax, ay, az, gx, gy, gz };
        sampleCount++;
      }
      haveAccel = false;
      haveGyro  = false;
    }
  }
  // If one half is left unpaired at the end of this burst, it's fine —
  // the next burst will pick up its partner. (At equal BDR this almost
  // never happens except at the edges of a burst boundary.)

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
  dev.setAccelDataRate(LSM6DS_RATE_416_HZ);
  dev.setGyroDataRate(LSM6DS_RATE_416_HZ);

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

  // Reset the sample buffer for this batch.
  sampleCount = 0;

  // Drain in bursts until the FIFO is empty.
  while (drainBurst() > 0) { }

  return sampleCount > 0;
}

uint16_t count()          { return sampleCount; }
const Sample* samples()   { return sampleBuf; }

}  // namespace imu
