# KiloGlide — Data Insights & Strategic Notes

Captured from review conversation. Companion to `decisions.md` and `firmware_roadmap.md`.

The name *kilo* is Hawaiian for observer — the patient, expert watching that traditional navigators used to read the stars, the sea, and the wind. KiloGlide is a kilo of paddling: a device whose job is to observe your glide and tell you, with discipline, what it sees.

That framing matters because it sets the product's voice. KiloGlide doesn't coach. It doesn't motivate. It observes and reports. The coaching happens between the paddler and the data, or between the paddler and a human coach reading the data together.

---

## Validation gaps to close before Wave 3 spend

The project has good intuition behind it, but the external validation so far is one paddler friend (Ray) and one technical critic. That's enough to start building, not enough to know strangers will pay or wear it.

**Action before spending on display + battery (~$130):** get logged data from a bare logger in front of two paddlers who aren't already in the circle. Show them traces, ask what's interesting. If independent paddlers converge on the same metric, that's signal. If they don't, the money's saved and the lesson's banked.

---

## Hardware risk: saltwater

Pelican 1010 is rated IP67 — splash and brief fresh-water immersion. Documented failure mode for marine electronics this size is salt creep through the pressure vent and around the seal across repeated wet/dry cycles. Two cheap mitigations:

- Conformal coat the assembled PCB (MG Chemicals 422B acrylic, ~$15)
- Bag the electronics inside the case in a heat-sealed mylar pouch with a small desiccant pack

Assume the case will eventually fail. Plan accordingly.

---

## Power budget (updated for 2000 mAh battery)

With 2000 mAh instead of 1200, energy budget is 67% larger — comfortable but still needs verification. The unknowns multiply quickly:

- IMU at 200–400 Hz with FIFO bursts
- GPS at 1–10 Hz (M10 is lower power than predecessors but still the largest single draw)
- microSD writes (transient ~100 mA spikes during flush)
- Frontlit LCD (frontlight is the big variable; most of the time it should be off)
- ESP32-S3 average current heavily dependent on WiFi/BT state

**Bench-measure before locking anything else.** Realistic duty cycle, full sensor suite running, log to SD, display on. Target: 4+ hours. Downwind runs go 2 hours; distance training goes 3+; race conditions need margin on top of that.

---

## Business model question

Sell it, open-source it, or just use it personally? The answer changes Wave 4 and beyond:

| Path | Implications |
|---|---|
| Personal tool | Optimize for learning. Skip cert, skip warranty, skip support. |
| Open-source hardware | Kills the moat but skips FCC/CE entirely. Community could compound the algorithms. |
| Commercial product | FCC intentional-radiator cert (~$3–5k), CE for Europe, warranty/returns/support. Real cost. |

Don't decide today — but notice which one the work is drifting toward, and whether that's the one you want.

---

## Data ideas: what actually helps paddlers

These are the metrics where the gyro + high-rate IMU let KiloGlide do things SpeedCoach structurally cannot. They're also where the *kilo* — the observer — earns its name. Each one represents something a paddler can't see for themselves and a coach can only see imperfectly from a chase boat.

### Asymmetry detection

The single highest-value insight for a recreational paddler. Almost everyone has a dominant side, almost no one knows by how much. With the gyro you can resolve any of:

- Roll amplitude per stroke (left vs. right)
- Force-curve area per stroke side
- Catch timing (how soon after the roll reversal the catch happens)
- Time-on-blade per side

NK's meters-per-stroke-side is a primitive proxy. The IMU gives you the underlying mechanics directly. Asymmetry is **coachable** — the moment a paddler sees a 12% area gap left-vs-right, they know what to work on.

### Catch and exit shape

Ray named exit; catch is the other thing coaches obsess over. Sub-stroke resolution from the IMU lets you characterize the leading edge of the acceleration curve:

- Slope (catch sharpness)
- Time-to-peak
- Peak position as a percentage of the stroke
- Decay shape on exit (the "checking" Ray flagged)

This is the metric that **fundamentally cannot exist on a GPS-only device**, because it requires resolution finer than one stroke. It's the clearest demonstration of why the product exists.

### Fatigue signature

Across a long piece, force curves narrow, asymmetry widens, and cadence drifts in characteristic patterns. A "fatigue index" derived from these — even a single number — flags when technique is degrading and training value has stopped accruing. It also gives coaches a metric they currently can't see from the chase boat.

### Run linking in downwind

The metric isn't "did you catch a wave," it's "did you stay on it, and did you transition cleanly to the next." Time-on-wave plus inter-run gap plus the pitch trace tells the whole story. SpeedCoach gives a number; KiloGlide can give the trace plus derived metrics:

- Catch success rate (attempts / catches)
- Catch latency (paddle-effort start → glide onset)
- Ride duration distribution
- Linking rate (rides where the next catch happens within N seconds)

### Interval repeatability

A paddler doing 6×500m doesn't just want splits — they want to know which pieces had matching technique. Correlation of normalized force curves across pieces is a single number that captures whether a session was technically clean. Coaches will pay attention to that.

---

## Design principles for the data layer

Two rules to hold against feature creep.

**On-water UI shows one or two real-time metrics, maximum.** Cadence + corrected DPS is plenty. The momentum curve should be a glanceable shape, not a number to read. A paddler with attention split across the boat, the water, and the display can absorb shape faster than digits.

**The post-session review is the actual product.** Real-time on the water is the hook. The session review is what makes a paddler open the app Tuesday morning. That's also where Josh lives — give him the artifacts that help him coach Ray remotely. The device is the sensor; the post-session view is the coach.

This biases firmware effort: log everything at full rate, render the on-water UI from a small subset, do the heavy analysis offline. Storage is cheap; algorithms developed in Python against logged sessions iterate 100× faster than algorithms developed against the live device.
