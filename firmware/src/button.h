// button.h — Session control button with short press and long press detection.
//
// A momentary pushbutton on GPIO 1 with internal pull-up. No external
// resistor needed — the ESP32-S3 has ~45 kohm internal pull-ups. Debounce
// is handled in software by the Bounce2 library (25 ms interval).
//
// Press detection:
//   Short press (< 2 s)  → write a user mark into the active session
//   Long press  (≥ 2 s)  → start or stop a logging session
//
// Mark is the easy gesture (quick tap while paddling). Session toggle is
// deliberate (hold 2 seconds on shore) so you can't accidentally kill a
// session mid-stroke.
//
// Typical use:
//   button::init();               // in setup()
//   button::update();             // in loop(), every iteration
//   switch (button::action()) {   // check what happened
//     case button::SHORT: ...     // mark
//     case button::LONG:  ...     // toggle session
//   }

#pragma once

#include <stdint.h>

namespace button {

// What the user did. Returned by action() and then cleared.
enum Action : uint8_t {
  NONE  = 0,
  SHORT = 1,   // quick tap — user mark
  LONG  = 2,   // hold 2 s — toggle session
};

// Set up GPIO 1 with internal pull-up and attach Bounce2 debouncer.
void init();

// Poll the debouncer and run the press-detection state machine.
// Call every loop() iteration — cheap, just reads a pin and checks timing.
void update();

// Return the most recent detected action and clear it. If nothing happened
// since the last call, returns NONE.
Action action();

}  // namespace button
