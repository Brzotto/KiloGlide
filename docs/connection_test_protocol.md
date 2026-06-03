# On-water protocol — Connection A/B test

**Goal:** prove whether KG's *connection* metric measures **technique** (how
cleanly you link the catch to the drive) or just **water/speed conditions**.
The only way to know is to vary technique *and nothing else*.

**Hypothesis:** at the same cadence in the same water, deliberately *connected*
strokes will read as a higher "connected %" (single clean force arch) than
deliberately *disconnected* (punchy/late/arm-y) strokes. If KG can separate
them, connection is a real, coachable metric. If it can't, it's measuring
conditions and we move on.

---

## Conditions (kill the confounds)
- **Calmest water you can find.** Flat removes the wave-slap confound that made
  session 37 ambiguous. Same stretch for every piece.
- **Same mount, same orientation** as previous sessions (breadboard forward of
  seat). Don't move it mid-session.
- Pick a time with minimal current change if possible (doesn't have to be zero —
  we hold cadence, not speed).

## Setup (do the KG part on shore — never open the box on the water)
1. **On shore, before launching:** long-press the KG button to start the
   session, then seal the box. KG logs the whole paddle; you won't touch it
   again until you're back on land. (We segment the data with the *Garmin*, so
   no KG button presses are needed on the water.)
2. On the **Garmin**, turn **auto-lap OFF** (Activity Settings → Laps → Manual).
   We want laps *only* where you press the button.
3. Start the SpeedCoach and the Garmin activity.
4. After launching, **sit still / glide for ~30 seconds** before paddling. KG
   uses this stationary window to find gravity and the boat axes — it makes the
   whole analysis more reliable. Don't skip it.
5. Warm up and settle into your target cadence — **~50 spm** is a good default
   (use the SpeedCoach live readout to lock it). This warm-up is Garmin lap 1
   and won't be analyzed.

## The A/B pieces
Hold **the same cadence (~50 spm) for every piece** — this is the whole point.
Vary only the catch:

- **A — connected:** long, committed catch. Lock the blade, load early and
  smoothly, drive with the body in one motion. Your "best technique."
- **B — disconnected:** deliberately punchy / late / arm-y. "Slip" the catch,
  then yank. Same cadence, same effort feel — just a sloppy link.

Do **3 of each, alternating**, ~2 minutes per piece:
`A1 → B1 → A2 → B2 → A3 → B3`

## Marking with the Garmin lap button (this is how the analysis finds pieces)
Each **lap-button press** starts a new Garmin lap. Press at **every boundary**,
paddling continuously (no rest, so each lap is a clean piece):

1. Warm up at cadence — this is **lap 1** (don't press yet).
2. **Lap** → start A1 → ~2 min connected.
3. **Lap** → start B1 → ~2 min disconnected.
4. **Lap** → start A2 … and so on, alternating.
5. After B3, **Lap** once more to start the cooldown lap.
6. Paddle home; back on shore, long-press KG to end the session.

That's **7 presses**, producing **8 laps**:
`lap1=warm-up, lap2=A1, lap3=B1, lap4=A2, lap5=B2, lap6=A3, lap7=B3, lap8=cooldown`.
So the label sequence for analysis is **`skip,A,B,A,B,A,B,skip`**.

> If you lose count, don't worry — note roughly when each piece happened and we
> can segment by time with `--windows` instead.

## Bring back
- KG binary log (`kg_0000NN.bin`)
- Garmin **TCX** export — **required** (it's how we segment the pieces now)
- SpeedCoach **CSV** export (per-stroke, like last time)

---

## What we compute afterward
`python analysis/connection_test.py --session NN --from-garmin --labels "skip,A,B,A,B,A,B,skip"`

(Adjust the labels to match how many warm-up/cooldown laps you actually had.)

It reports, per piece: cadence, connected %, lull depth, drive/catch ratio — and
a grouped A-vs-B summary.

**Success criterion:** with cadence matched (check the `cad` column — A and B
should be within a couple spm), the A pieces show a **clearly higher connected
%** than the B pieces, and it repeats across the 3 reps. That would be the first
hard evidence that KG measures something a SpeedCoach can't: *how you paddle,
not just how fast.*
