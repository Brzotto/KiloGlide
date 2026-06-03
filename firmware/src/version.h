#pragma once

// KiloGlide firmware version.
//
// Bump this on any meaningful firmware change. It is printed over serial at
// boot (with the compile date/time) so you can confirm at a glance which build
// is actually running on the device — this is what catches a stale or failed
// flash, where old code keeps running after an "upload" that didn't take.
//
// History:
//   0.3.0 — GPS TIME anchor, fix-transition events, real heading, hardened
//           SD/FIFO logging diagnostics (post-2026-05-23 firmware). This build
//           predates versioning, so it is not stamped into logs.
//   0.4.0 — Print firmware version at boot; stamp it into the log header
//           (formerly reserved bytes) so every session self-identifies.
#define KG_FIRMWARE_VERSION "0.4.0"
