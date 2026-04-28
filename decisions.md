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

**Decision:** validate the design on breadboard before committing to PCB.

**Why this changed:** initial preference was PCB-first to avoid messy wiring on the boat. Reasonable from an aesthetics/reliability angle, but the deeper reason for breadboard-first is that there are too many unknowns that only get answered by running real hardware: LCD timing quirks, current draw under load, GPS first-fix performance in local conditions, IMU bus sharing behavior, mounting position effects on signal quality. Discovering these on a $50 PCB means a respin; discovering them on a breadboard means a wire change.

**Mitigation for the "wires in a boat" concern:** the breadboard never goes near the water in v0. Algorithm development happens at the bench. Once the design is proven, the v1 PCB is built with confidence.

**Hardware continuity rule:** every chip used on the breadboard is the same chip that goes onto v1 PCB. Only the form factor changes (DevKit → bare module, breakout → bare IC). This means firmware doesn't change between stages.

---

## Hardware selections (locked in for v0/breadboard)

| Function | Chip | Breadboard form | PCB form |
|---|---|---|---|
| MCU | ESP32-S3 | DevKitC-1 N8R8 | WROOM-1 module |
| IMU | ICM-42688-P | LogicalEdges Tindie breakout | bare LGA |
| GPS | u-blox MAX-M10S | SparkFun breakout | bare LCC module |
| Display | Sharp LS027B7DH01 | Adafruit 2.7" breakout | bare panel + driver |
| Storage | microSD | Adafruit breakout | Hirose DM3AT socket |
| Charging | TP4056 | Amazon module | bare IC + USB-C + protection |

**ESP32-S3 over alternatives:** picked for built-in BLE 5.0 (Garmin sync path), Wi-Fi (later phone sync), enough GPIOs for everything, and abundant Arduino/ESP-IDF library support. Modular FCC certification on WROOM-1 carries through to product PCB, saving cert costs later.

**ICM-42688-P over alternatives:** industry-leading noise floor for the price, ±2g to ±16g configurable accelerometer range (handles both light dragon-boat hull responses and sharp OC1 sprints), 6-axis is sufficient for now. Magnetometer (9-axis) skipped for v1 — see GPS heading note below.

**MAX-M10S over alternatives:** quad-constellation (GPS + GLONASS + Galileo + BeiDou) on a single die, very low power (~25 mW continuous), small footprint, well-supported by SparkFun u-blox library. Lifecycle status to verify with u-blox before PCB v1 commit; MAX-M10M-00B noted as a footprint-compatible backup.

**Sharp Memory LCD:** sunlight-readable without backlight, low power, slow refresh is fine for paddling display. Viewing angle and dawn/dusk readability flagged for verification before PCB v1.

---

## Hardware decisions corrected from earlier in the design

These are corrections from a critique that caught real errors:

**Power regulation: AMS1117 is OUT for v1 PCB.** AMS1117 has ~1V dropout, which means it can't regulate cleanly to 3.3V once the LiPo sags below ~4.3V. A LiPo spends most of its discharge between 3.7V and 3.5V. AMS1117 would either fail or pass through unregulated voltage during normal use. Replacement: TPS63020 buck-boost (or similar) that produces stable 3.3V from 2.5–5.5V input at ~95% efficiency, gets the full LiPo discharge curve. Adds ~$3 to the PCB BOM but removes a real functional risk. For breadboard, the DevKit's onboard regulator is fine.

**Pelican 1010 is polycarbonate, NOT polypropylene.** Earlier mounting plan called for flame-treating the case to improve VHB adhesion. That's a recipe for polyolefins. PC bonds well with VHB after just an isopropyl wipe. Skip the flame treatment.

**Pelican already has a pressure equalization vent** (ePTFE membrane, factory-installed). Do not drill additional vents. Do not add a separate Gore patch. Don't compromise the IP67 rating.

**"Power" language dropped from metric vocabulary.** Calling boat acceleration × mass "power per stroke" is technically defensible as an impulse proxy, but borrows the credibility that cycling/rowing have earned through ergometer-validated power meters. Athletes who've trained with real power meters will notice. Better terminology: stroke impulse, boat response, effective drive, acceleration contribution, corrected DPS. Save "power" for if/when there's ergometer-validated calibration data to back it up.

**True Stroke Power demoted from headline metric to offline analysis** for v1. The risk of shipping a beautiful but unvalidated number where athletes train against misleading feedback for a season is real. v1 displays the known-good metrics (speed, split, rate, time, GPS quality, battery) only. Raw IMU + GPS log at full rate to SD card. TSP development happens in Python against logged data. Display it on-device only after correlation with something real has been demonstrated across many sessions.

---

## Mounting approach

**Case: Pelican 1010 micro case** (interior 111 × 73 × 43 mm, IP67, polycarbonate, ePTFE vent built in). Used both for v0 breadboard testing and as a candidate v1 production case.

**NK SpeedCoach mount compatibility.** NK sells the bracket (female receiver) but not the male dovetail backplate as a standalone accessory; the dovetail is molded into the SpeedCoach housing. Strategy: buy the NK adjustable surface mount (~$25 from nksports.com) and 3D-print the male dovetail using calipers off a friend's SpeedCoach. Print in PETG/ABS, mechanically fasten to a backing plate, VHB the backing plate to the Pelican (PC + IPA wipe + VHB 5952). Backing plate approach allows replacing the mount style without destroying the case.

**Latch orientation matters.** The Pelican's latch is on the long edge. Mount orientation must put the latch upward or athwartship, not down against the hull, or the case can't be opened without unmounting.

**Buttons accessed by opening case** (v0 decision). USB-C also only accessible when case is open. Fully sealed during use, opened to charge or interact. Acceptable trade-off for v1; revisit for production.

---

## Form factor and depth budget

PCB usable footprint inside Pelican 1010: ~89 × 61 mm with margins for foam, cables, and clearance. Hard cap around 102 × 66 mm. Smaller is fine and cheaper at OSHPark.

**Depth is tighter than area.** 43 mm interior must fit: LCD (6 mm) + LCD-to-PCB clearance (4 mm) + PCB (1.6 mm) + tallest component (3 mm) + battery (~6 mm with 1500–2000 mAh pouch) + foam. Battery pouch thickness is the swing variable. 1200–2000 mAh range is the right target — not a 3000 mAh, despite the original BOM specifying it.

**OSHPark cost** at $5/sq-in for 3-board panels: ~$36–55 for realistic v1 board sizes. Not the $20 originally written in the BOM.

---

## Algorithm-first prioritization

The hardest part of this project is not hardware. It's algorithms: stroke detection that works across paddlers, boats, mounting positions, and water conditions; mount-orientation calibration; distinguishing strokes from wave events; environment-corrected metrics. Hardware will work. The question is whether the metrics it produces are trustworthy.

**Plan:** v0 firmware logs raw IMU at 100–200 Hz and GPS at 5 Hz to SD card. No on-device metric computation beyond what's needed for the live display (speed, rate, time, status). Algorithms developed in Python against logged sessions, then ported to firmware once validated.

**Validation rubric (definition of done for "this is a product, not a project"):**

1. Survives water sessions (no leaks, no resets, no data loss)
2. Logs clean raw data (consistent sample rates, synchronized timestamps, no GPS dropouts mishandled)
3. Stroke detection agrees with video/manual counting across multiple paddlers
4. Speed/split agrees reasonably with NK SpeedCoach as reference
5. Same paddler/crew, same effort, same conditions → repeatable metrics
6. Corrected DPS metric is more stable across wind/current/chop than raw DPS

Until these are true, this is a cool electronics project. Once they're true, it becomes a product.

---

## Use-case priorities

Three distinct profiles, same hardware, different firmware modes selectable at startup:

**OC mode (primary v1).** Single paddler, narrow hull, large roll signal, glide-dominant performance lever. Primary metrics: speed, split, stroke rate, glide quality, roll, corrected DPS (offline initially).

**Dragon Boat mode (v1.5).** Wide hull, low roll, large mass, lateral sync as the dominant signal. Primary metrics: collective stroke rate, sync score, drum tempo (if MEMS mic added later), boat response per stroke. Coach gets full data; crew sees collective metrics only — frame as "what the boat is telling us," not surveillance.

**Surf mode (v2).** Downwind / ocean swell riding in OC. Different metrics entirely: catch success rate, catch latency, ride duration, top wave speed, linking rate, time above cruise speed. This is the use case that *most differentiates* Kikaha Coach from SpeedCoach — SpeedCoach is bad for surfing because speed/cadence don't tell you about catch quality. The Hawaii / Maui / Pacific NW downwind communities are exactly the niche-passionate market that buys high-end paddle gear. Surf mode might be the most distinctive marketable application of the whole project, even though OC flat-water is the entry point.

---

## Business model thinking (early, not committed)

**Customer is probably not the individual paddler — it's the coach, club, or program.** Dragon boat clubs in particular have budgets that recreational paddlers don't. A $400–500 device sold to a club for crew analytics is easier than 20 × $30 wearables sold to individuals. The coach pitch is: one boat unit + analytics platform, sold as a coaching tool, not a fitness gadget.

**Patent strategy: defer.** Individual components are not patentable (prior art everywhere). Specific combinations and the lineup-optimization angle may be. At this stage, trade secrets + first-mover trust + open-sourcing hardware while keeping analytics proprietary is the right model. Patents cost $10–15K and years; not the current bottleneck.

---

## What's next (immediate)

1. Order all breadboard parts (~$165: SparkFun, Adafruit, Tindie, Amazon, DigiKey)
2. Order Pelican 1010 (Amazon) and NK adjustable surface mount (nksports.com)
3. Set up Arduino IDE with ESP32 board package + required libraries
4. Set up Python environment for offline data analysis
5. Send Josh the pitch message — don't wait for hardware to be working
6. Take photos and write entries here as decisions get made

---

## Open questions to resolve before PCB v1

- MAX-M10S lifecycle status — verify with u-blox directly
- Sharp Memory LCD viewing angle from paddler's seated position — verify with breadboard mounted in case
- Real current draw under load — measure once breadboard is running
- Stroke detection algorithm validation across paddlers — needs water data
- Whether to put USB-C externally accessible (compromises seal) or only when case is open (current plan)
- Mount calibration UX — how does the paddler tell the device "now I'm aligned with the boat"
- Whether to add a magnetometer for heading on v2 (skipped v1; revisit if heading-dependent metrics turn out to matter)

---

*First entry: project named, approach committed, parts list locked. From here, every decision, mistake, surprise, and water test gets a new entry above this one.*
