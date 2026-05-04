# Kikaha Coach — Decisions Log

A running record of decisions made on the Kikaha Coach project, what alternatives were considered, and why each choice landed where it did. New entries go at the top. Past-me explains things to future-me so I don't have to re-derive context six months later.

---

## Project identity

**Name: Kikaha Coach.** Hawaiian *kīkaha* (KEE-kah-hah): to soar, glide, poise, skim along — as the frigate bird (ʻiwa). The frigate bird is the master of efficient flight, riding wind and momentum with minimal effort. That's the metaphor for what a great paddler does: efficient gliding through skilled reading of conditions. "Coach" positions the device as a coaching tool, not a fitness tracker. Leaves room for product line extension: Kikaha Crew (per-paddler wearables), Kikaha Connect (phone app), Kikaha Lab (cloud analytics), Kikaha Pro (premium tier).

Spelling note: marketing/UI uses "Kikaha" (no kahakō) for typability. About page and origin contexts use proper "Kīkaha" with explanation. Aim to honor the Hawaiian root without making non-paddlers fight diacritics.

To do before locking the name commercially: USPTO TESS check (classes 9 and 28), domain availability (kikaha.com, kikahacoach.com, kikaha.app), social handles (@kikaha, @kikahacoach across platforms). Run the name past Hawaiian paddlers in the community before any public launch.

---

## Core thesis

This is not a cheaper SpeedCoach. The wedge is "the device NK should have built" — purpose-designed for paddle sports, measuring things coaches argue about but cannot currently quantify. Price positioning is around $250–500 retail eventually, not a budget play; cheapness is not the value proposition.

The single most valuable insight in the project is **environment-corrected stroke contribution** (working name: True Stroke Power, but "power" language is dropped — see below). Distance-per-stroke conflates paddler effort with environmental forces. By using the glide phase between strokes as a continuously-updating environmental baseline, the device can isolate what the paddler's stroke actually contributed to boat motion, separately from wind, current, and chop. This is a metric no commercial device offers and is genuinely the breakthrough.

Strategic implication: the box is not the product. The dataset and the algorithms are the product. The box gets the device onto the boat.

---

## Approach: breadboard first, PCB second

**Decision:** validate the design on breadboard/perfboard before committing to PCB.

**Why this changed:** initial preference was PCB-first to avoid messy wiring on the boat. Reasonable from an aesthetics/reliability angle, but the deeper reason for breadboard-first is that there are too many unknowns that only get answered by running real hardware: LCD timing quirks, current draw under load, GPS first-fix performance in local conditions, IMU bus sharing behavior, mounting position effects on signal quality. Discovering these on a $50 PCB means a respin; discovering them on a perfboard means a wire change.

**Mitigation for the "wires in a boat" concern:** the breadboard never goes near the water in v0. Algorithm development happens at the bench. The perfboard prototype goes in a sealed Pelican case for water testing. Once the design is proven, the v1 PCB is built with confidence.

**Hardware continuity rule:** chips used on the perfboard should ideally be the same chips that go onto v1 PCB, or close equivalents with matching libraries.

---

## Hardware selections (locked in for v0/perfboard prototype)

| Function | Chip | Prototype form (v0) | PCB form (v1) |
|---|---|---|---|
| MCU | ESP32-S3 | DevKitC-1 N8R8 | WROOM-1 module |
| IMU | LSM6DSOX | Adafruit breakout | bare LGA (ICM-42688-P) |
| GPS | u-blox SAM-M10Q | SparkFun Qwiic breakout | bare LCC module |
| Display | Sharp LS027B7DH01A | Kuzyatech A2 (w/ boost) | bare panel + driver |
| Storage | microSD | Adafruit breakout | Hirose DM3AT socket |
| Charging | bq25185 | Adafruit module (w/ boost)| bare IC + USB-C + protection |

**ESP32-S3 over alternatives:** picked for built-in BLE 5.0 (Garmin sync path), Wi-Fi (later phone sync), enough GPIOs for everything, and abundant Arduino/ESP-IDF library support. Modular FCC certification on WROOM-1 carries through to product PCB, saving cert costs later.

**LSM6DSOX (v0) vs ICM-42688-P (v1):** The prototype is using the LSM6DSOX via Adafruit for ease of prototyping and library support. The production PCB will swap to the ICM-42688-P for its industry-leading noise floor for the price.

**SAM-M10Q over alternatives:** Used for the v0 prototype specifically because it features a built-in patch antenna, eliminating the need for an external antenna inside the tight Pelican case enclosure. It remains low power and quad-constellation.

**Sharp Memory LCD:** sunlight-readable without backlight, low power, slow refresh is fine for paddling display. The v0 prototype requires the Kuzyatech breakout *with boost* to step up the 3.3V LiPo power to the 5V required by the panel.

---

## Hardware decisions corrected from earlier in the design

These are corrections from a critique that caught real errors:

**Power regulation: AMS1117 is OUT for v1 PCB.** AMS1117 has ~1V dropout, which means it can't regulate cleanly to 3.3V once the LiPo sags below ~4.3V. A LiPo spends most of its discharge between 3.7V and 3.5V. Replacement: TPS63020 buck-boost (or similar) that produces stable 3.3V from 2.5–5.5V input at ~95% efficiency. For the perfboard, the DevKit's onboard regulator and the bq25185 charger module handle power.

**Pelican 1010 is polycarbonate, NOT polypropylene.** Earlier mounting plan called for flame-treating the case to improve VHB adhesion. PC bonds well with VHB after just an isopropyl wipe. Skip the flame treatment.

**Pelican already has a pressure equalization vent** (ePTFE membrane, factory-installed). Do not drill additional vents. Do not add a separate Gore patch. Don't compromise the IP67 rating.

**"Power" language dropped from metric vocabulary.** Calling boat acceleration × mass "power per stroke" is technically defensible as an impulse proxy, but borrows the credibility that cycling/rowing have earned through ergometer-validated power meters. Better terminology: stroke impulse, boat response, effective drive, acceleration contribution, corrected DPS.

**True Stroke Power demoted from headline metric to offline analysis** for v1. The risk of shipping a beautiful but unvalidated number where athletes train against misleading feedback for a season is real. v1 displays the known-good metrics only. Raw IMU + GPS log at full rate to SD card. TSP development happens in Python against logged data.

---

## Mounting approach

**Case: Pelican 1010 micro case** (interior 111 × 73 × 43 mm, IP67, polycarbonate, ePTFE vent built in). Used both for v0 perfboard testing and as a candidate v1 production case.

**NK SpeedCoach mount compatibility.** Strategy: buy the NK adjustable surface mount (~$25 from nksports.com) and 3D-print the male dovetail. Print in PETG/ABS, mechanically fasten to a backing plate, VHB the backing plate to the Pelican (PC + IPA wipe + VHB 5952).

**Latch orientation matters.** The Pelican's latch is on the long edge. Mount orientation must put the latch upward or athwartship, not down against the hull.

**Buttons accessed by opening case** (v0 decision). Fully sealed during use, opened to charge or interact. Acceptable trade-off for v1; revisit for production.

---

## Form factor and depth budget

**Perfboard fit:** The Adafruit Perma-Proto Half-Size (82x53mm) comfortably fits the 111x73mm interior of the Pelican 1010.

**Depth is tighter than area.** 43 mm interior must fit the entire stack. Current v0 estimations place the depth at ~34mm, leaving enough clearance so nothing is crushed. Battery size is 2000mAh, deferred until initial bench testing is complete. 

---

## Algorithm-first prioritization

The hardest part of this project is not hardware. It's algorithms. Hardware will work. The question is whether the metrics it produces are trustworthy.

**Plan:** v0 firmware logs raw IMU at 100–200 Hz and GPS at 5 Hz to SD card. No on-device metric computation beyond what's needed for the live display (speed, rate, time, status). Algorithms developed in Python against logged sessions, then ported to firmware once validated.

**Validation rubric (definition of done for "this is a product, not a project"):**

1. Survives water sessions (no leaks, no resets, no data loss)
2. Logs clean raw data (consistent sample rates, synchronized timestamps, no GPS dropouts mishandled)
3. Stroke detection agrees with video/manual counting across multiple paddlers
4. Speed/split agrees reasonably with NK SpeedCoach as reference
5. Same paddler/crew, same effort, same conditions → repeatable metrics
6. Corrected DPS metric is more stable across wind/current/chop than raw DPS

---

## Use-case priorities

Three distinct profiles, same hardware, different firmware modes selectable at startup:

**OC mode (primary v1).** Single paddler, narrow hull, large roll signal, glide-dominant performance lever. 

**Dragon Boat mode (v1.5).** Wide hull, low roll, large mass, lateral sync as the dominant signal. 

**Surf mode (v2).** Downwind / ocean swell riding in OC. Different metrics entirely: catch success rate, catch latency, ride duration, top wave speed. This is the use case that *most differentiates* Kikaha Coach from SpeedCoach.

---

## Business model thinking (early, not committed)

**Customer is probably not the individual paddler — it's the coach, club, or program.** A $400–500 device sold to a club for crew analytics is easier than 20 × $30 wearables sold to individuals. 

**Patent strategy: defer.** Trade secrets + first-mover trust + open-sourcing hardware while keeping analytics proprietary is the right model currently.

---

## What's next (immediate)

1. Order ESP32 DevKit, IMU, and perfboard FIRST to start coding.
2. Order remaining BOM items.
3. Order Pelican 1010 (Amazon) and NK adjustable surface mount (nksports.com)
4. Set up Arduino IDE with ESP32 board package + required libraries
5. Set up Python environment for offline data analysis
6. Send Josh the pitch message — don't wait for hardware to be working

---

## Open questions to resolve before PCB v1

- MAX-M10S lifecycle status (if reverting from SAM-M10Q for production)
- Sharp Memory LCD viewing angle from paddler's seated position
- Real current draw under load — measure once perfboard is running
- Stroke detection algorithm validation across paddlers — needs water data
- Mount calibration UX — how does the paddler tell the device "now I'm aligned with the boat"