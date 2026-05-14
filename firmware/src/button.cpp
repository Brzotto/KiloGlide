// button.cpp — Debounced button with single/double press detection.
//
// Wiring: one side of the button to GPIO 1, other side to GND. The internal
// pull-up holds the pin HIGH when the button is open; pressing it pulls LOW.
// The Bounce2 library filters out the mechanical chatter (bouncing) that
// happens in the first ~10-20 ms after a press or release.

#include "button.h"

#include <Arduino.h>
#include <Bounce2.h>

namespace {

constexpr uint8_t BUTTON_PIN = 1;

// How long to wait after a first press before deciding it was a single press
// (not the start of a double press). 400 ms is fast enough to feel responsive
// but slow enough that two deliberate taps register as a double.
constexpr unsigned long DOUBLE_PRESS_WINDOW_MS = 400;

// Bounce2 debounce interval. 25 ms filters typical tactile switch bounce
// without making the button feel sluggish.
constexpr uint8_t DEBOUNCE_MS = 25;

Bounce btn;

uint8_t pressCount = 0;
unsigned long firstPressTime = 0;
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

  // fell() = HIGH-to-LOW transition = button pressed (pull-up wiring).
  if (btn.fell()) {
    pressCount++;
    if (pressCount == 1) {
      firstPressTime = millis();
    } else if (pressCount >= 2) {
      // Two presses within the window → double press.
      pendingAction = DOUBLE;
      pressCount = 0;
    }
  }

  // If one press happened and the window has expired without a second,
  // it's a single press.
  if (pressCount == 1 &&
      (millis() - firstPressTime) > DOUBLE_PRESS_WINDOW_MS) {
    pendingAction = SINGLE;
    pressCount = 0;
  }
}

Action action() {
  Action a = pendingAction;
  pendingAction = NONE;
  return a;
}

}  // namespace button
