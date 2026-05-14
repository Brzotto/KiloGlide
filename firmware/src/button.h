// button.h — Session control button with single/double press detection.
//
// A momentary pushbutton on GPIO 1 with internal pull-up. No external
// resistor needed — the ESP32-S3 has ~45 kohm internal pull-ups. Debounce
// is handled in software by the Bounce2 library (25 ms interval).
//
// Press detection:
//   Single press → start or stop a logging session
//   Double press → write a user mark into the active session
//
// Single press has a 400 ms delay before being reported, because the module
// has to wait that long to confirm a second press isn't coming. That's fine
// for session start/stop — you won't notice 400 ms.
//
// Typical use:
//   button::init();               // in setup()
//   button::update();             // in loop(), every iteration
//   switch (button::action()) {   // check what happened
//     case button::SINGLE: ...
//     case button::DOUBLE: ...
//   }

#pragma once

#include <stdint.h>

namespace button {

// What the user did. Returned by action() and then cleared.
enum Action : uint8_t {
  NONE   = 0,
  SINGLE = 1,   // one press — toggle session
  DOUBLE = 2,   // two presses — user mark
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
