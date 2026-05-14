// button.cpp — Debounced button with short/long press detection.
//
// Wiring: one side of the button to GPIO 1, other side to GND. The internal
// pull-up holds the pin HIGH when the button is open; pressing it pulls LOW.
// The Bounce2 library filters out the mechanical chatter (bouncing) that
// happens in the first ~10-20 ms after a press or release.
//
// Detection logic:
//   - On press-down (fell): record the time.
//   - While held: if held ≥ LONG_PRESS_MS, fire LONG immediately and set a
//     flag so we don't also fire SHORT on release.
//   - On release (rose): if LONG didn't already fire, it was a SHORT press.

#include "button.h"

#include <Arduino.h>
#include <Bounce2.h>

namespace {

constexpr uint8_t BUTTON_PIN = 1;

// How long you must hold the button before it counts as a long press.
// 2 seconds is deliberate enough to prevent accidental session toggles
// from bumps or splashes, but short enough that it doesn't feel sluggish.
constexpr unsigned long LONG_PRESS_MS = 2000;

// Bounce2 debounce interval. 25 ms filters typical tactile switch bounce
// without making the button feel sluggish.
constexpr uint8_t DEBOUNCE_MS = 25;

Bounce btn;

unsigned long pressDownTime = 0;   // millis() when button was pressed down
bool buttonHeld = false;           // true while the button is physically down
bool longFired  = false;           // true if we already fired LONG for this press
button::Action pendingAction = button::NONE;

}  // namespace

namespace button {

void init() {
  // Pass the pin mode directly to Bounce2. If you call pinMode() separately
  // and then attach(pin), Bounce2 overrides it with plain INPUT (no pull-up)
  // and the pin floats.
  btn.attach(BUTTON_PIN, INPUT_PULLUP);
  btn.interval(DEBOUNCE_MS);
}

void update() {
  btn.update();

  // fell() = HIGH-to-LOW transition = button pressed down (pull-up wiring).
  if (btn.fell()) {
    pressDownTime = millis();
    buttonHeld = true;
    longFired = false;
  }

  // While held, check if we've crossed the long-press threshold.
  // Fire LONG as soon as we cross it — don't wait for release.
  // This gives immediate feedback: the user holds the button, the LED
  // changes after 2 seconds, and they know they can let go.
  if (buttonHeld && !longFired &&
      (millis() - pressDownTime) >= LONG_PRESS_MS) {
    pendingAction = LONG;
    longFired = true;
  }

  // rose() = LOW-to-HIGH transition = button released.
  if (btn.rose()) {
    // If long press didn't fire during the hold, it was a short press.
    if (!longFired) {
      pendingAction = SHORT;
    }
    buttonHeld = false;
  }
}

Action action() {
  Action a = pendingAction;
  pendingAction = NONE;
  return a;
}

}  // namespace button
