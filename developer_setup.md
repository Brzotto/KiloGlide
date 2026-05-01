# Kikaha Coach — Developer Setup Guide

A walkthrough for getting from "I can write firmware" to "I have a proper development environment with version control, dependency management, and a sane workflow." Written assuming you're comfortable with C/C++, registers, and peripherals, but new to git, package managers, and modern project structure.

If you've ever zipped a folder named `firmware_v2_FINAL_actually_final.zip`, this guide is for you.

---

## Mental model: why this stuff matters even when you're solo

The single most important thing software tooling buys you is **fearlessness**. You can rip out a working subsystem to try a different approach, and if it's worse, one command puts everything back. You can leave a half-working idea on a branch for two weeks while you work on something else, and pick it up exactly where you left it. You can look at a working build and ask "what changed since last week?" and get an exact answer.

EE work without these tools means you keep things working by being careful. EE work with them means you keep things working by being able to undo. Careful breaks down on big projects; undo doesn't.

The cost is one week of awkward fumbling while the muscle memory builds. After that, it's invisible.

---

## One-time installs

You only do this once per machine. Total time: 30 minutes if nothing fights you.

### 1. Git

Mac: comes preinstalled, or `brew install git`.
Linux: `sudo apt install git` (Debian/Ubuntu) or equivalent.
Windows: download from [git-scm.com](https://git-scm.com), accept defaults.

Configure your identity once — every commit is signed with this:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global pull.rebase false
```

The last two settle minor configuration questions in advance so git doesn't ask you about them later.

### 2. VSCode

Download from [code.visualstudio.com](https://code.visualstudio.com). Other editors work, but PlatformIO is best supported in VSCode and the integration genuinely matters.

### 3. PlatformIO extension

Inside VSCode, go to the Extensions panel (square icon on the left), search "PlatformIO IDE", install. It will spend a few minutes installing its toolchain on first launch — let it finish before doing anything else.

### 4. Python

You'll want this for the analysis side. Python 3.10+ is fine.

Mac: `brew install python@3.11`
Linux: usually preinstalled; otherwise `sudo apt install python3 python3-venv python3-pip`
Windows: download from [python.org](https://python.org), check "Add to PATH" during install

### 5. GitHub account

Create one at [github.com](https://github.com) if you don't have it. Free tier is fine; private repos are unlimited. Set up SSH keys so you don't have to type a password every push:

```bash
ssh-keygen -t ed25519 -C "you@example.com"
# Press enter to accept defaults; optionally set a passphrase
cat ~/.ssh/id_ed25519.pub
```

Copy that public key, paste it into GitHub → Settings → SSH and GPG keys → New SSH key. Test it:

```bash
ssh -T git@github.com
# Should say "Hi <username>! You've successfully authenticated..."
```

---

## Create the repo

Two paths. Pick one — they end in the same place.

### Path A: GitHub first, then clone

This is the simpler path for beginners.

1. Go to GitHub, click the green "New" button (or [github.com/new](https://github.com/new))
2. Repository name: `kikaha-coach`
3. Set it to **Private**
4. Check "Add a README file" — gives you something to start with
5. Add a `.gitignore` from the dropdown — pick "C++" (we'll customize it)
6. Click "Create repository"
7. On the repo page, click the green "Code" button → SSH → copy the URL
8. In your terminal:

```bash
cd ~/Projects   # or wherever you keep code
git clone git@github.com:yourusername/kikaha-coach.git
cd kikaha-coach
```

You now have a local copy synced with GitHub.

### Path B: Local first, then push

If you already have files locally you want to preserve:

```bash
mkdir kikaha-coach && cd kikaha-coach
git init
# ... create files ...
git add .
git commit -m "Initial commit"
# Then create empty repo on GitHub (don't add README), and:
git remote add origin git@github.com:yourusername/kikaha-coach.git
git branch -M main
git push -u origin main
```

---

## Project structure

In your `kikaha-coach` directory, set up this layout:

```
kikaha-coach/
├── README.md
├── .gitignore
├── platformio.ini
├── firmware/
│   ├── src/
│   │   └── main.cpp
│   └── include/
├── tools/
├── analysis/
├── docs/
│   ├── decisions.md
│   ├── data_insights.md
│   ├── firmware_roadmap.md
│   ├── developer_setup.md
│   └── log_format.md
└── sessions/        # gitignored — water test logs go here
```

You can create it all at once:

```bash
mkdir -p firmware/src firmware/include tools analysis docs sessions
touch firmware/src/main.cpp
```

Drop your existing `decisions.md`, `data_insights.md`, and `firmware_roadmap.md` into `docs/`.

---

## Starter file contents

Copy each block into the named file.

### `.gitignore`

This tells git which files **not** to track. Build outputs, log files from your water tests, editor temp files, OS metadata. The rule: if a file is generated from other files, or contains data not meant for sharing, it doesn't belong in git.

```gitignore
# PlatformIO build artifacts
.pio/
.pioenvs/
.piolibdeps/
*.elf
*.hex
*.bin
*.map

# VSCode (keep settings.json shareable, ignore the rest)
.vscode/.browse.c_cpp.db*
.vscode/c_cpp_properties.json
.vscode/launch.json
.vscode/ipch

# Python
__pycache__/
*.pyc
*.pyo
.ipynb_checkpoints/
.venv/
venv/
env/

# Session logs — these are user data, not source code
sessions/
*.log

# Jupyter outputs (large, change every run)
*-checkpoint.ipynb

# OS metadata
.DS_Store
Thumbs.db
desktop.ini

# Editor temp/backup files
*~
*.swp
*.swo
.idea/

# Secrets — never commit these
.env
secrets.h
```

### `platformio.ini`

This is the PlatformIO project configuration. Think of it as a Makefile + dependency manifest combined into something readable.

```ini
[env:esp32-s3-devkitc-1]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino

monitor_speed = 115200
monitor_filters = esp32_exception_decoder, time
upload_speed = 921600

build_flags =
    -DCORE_DEBUG_LEVEL=3
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1

board_build.partitions = default_8MB.csv
board_upload.flash_size = 8MB
board_build.arduino.memory_type = qio_opi

lib_deps =
    adafruit/Adafruit LSM6DS
    adafruit/Adafruit BusIO
    adafruit/Adafruit SHARP Memory Display
    sparkfun/SparkFun u-blox GNSS v3
    greiman/SdFat
    thomasfredericks/Bounce2

[env:esp32-s3-devkitc-1-debug]
extends = env:esp32-s3-devkitc-1
build_type = debug
build_flags =
    ${env:esp32-s3-devkitc-1.build_flags}
    -DCORE_DEBUG_LEVEL=5
    -DKIKAHA_DEBUG=1
```

A few notes on what's happening here:

- `[env:...]` defines a build environment. You can have multiple — production, debug, simulator. Switch between them with `pio run -e <name>`.
- `lib_deps` lists Arduino libraries. PlatformIO downloads and pins them automatically. You don't manually copy library folders around like in old Arduino IDE.
- The board target tells PlatformIO which MCU you have so it picks the right toolchain and memory layout.
- `build_flags` are `#define`s passed to the compiler. `KIKAHA_DEBUG=1` lets you write `#ifdef KIKAHA_DEBUG` blocks that only compile in debug builds.
- The second environment **extends** the first — same settings, different overrides. This is how you avoid duplicating configuration.

### `firmware/src/main.cpp`

A blinky to verify your whole toolchain works on day 1. The dev kit has an onboard RGB LED on GPIO 48.

```cpp
#include <Arduino.h>

// ESP32-S3-DevKitC-1 has an onboard RGB LED on GPIO 48.
// We'll use it as our "I am alive" indicator.
#define LED_PIN 48

void setup() {
    Serial.begin(115200);
    delay(2000);  // Give USB-CDC time to enumerate so we don't miss boot logs
    Serial.println("Kikaha Coach firmware booting...");

    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("blink");
    delay(500);
    digitalWrite(LED_PIN, LOW);
    delay(500);
}
```

If the RGB LED is addressable (NeoPixel-style), the above won't blink it visibly. On the N8R8 variant, the onboard LED is a single addressable WS2812 — you'd use the `Adafruit NeoPixel` library instead. Check your specific board; the dev kit has gone through revisions. If `digitalWrite` doesn't visibly do anything, that's the reason. We can swap to NeoPixel code on day 1 if needed.

### `README.md`

This is the front door of your repo. It tells future-you (and any collaborator) what this is and how to use it.

```markdown
# Kikaha Coach

Open-water paddling coach for canoe/SUP downwind and distance training.
ESP32-S3 + LSM6DSOX IMU + u-blox GPS + Sharp memory LCD, in a Pelican 1010 case.

## Status

Early hardware bring-up. See `docs/firmware_roadmap.md` for the staged plan.

## Documents

- [`docs/decisions.md`](docs/decisions.md) — running log of project decisions
- [`docs/data_insights.md`](docs/data_insights.md) — data ideas and design principles
- [`docs/firmware_roadmap.md`](docs/firmware_roadmap.md) — staged firmware development plan
- [`docs/developer_setup.md`](docs/developer_setup.md) — dev environment setup
- [`docs/log_format.md`](docs/log_format.md) — binary session log spec (TBD)

## Building

Requires PlatformIO. From the repo root:

```bash
pio run                      # build
pio run -t upload            # build + flash
pio device monitor           # serial console
```

## Repo layout

- `firmware/` — ESP32 firmware (PlatformIO project)
- `tools/` — Python utilities (log parser, fake data generator)
- `analysis/` — Jupyter notebooks for algorithm development
- `docs/` — design and decision documents
- `sessions/` — raw water-test logs (gitignored)

## License

TBD.
```

---

## The daily loop

Once setup is done, your day-to-day looks like this. Memorize the four-step rhythm; everything else is variation.

### 1. Pull (start of session)

```bash
cd ~/Projects/kikaha-coach
git pull
```

If you only work on one machine, this is a no-op most of the time. Do it anyway — the muscle memory matters when you eventually work across machines or with collaborators.

### 2. Edit, build, test

In VSCode with the PlatformIO extension active:

- Edit code
- Build: PlatformIO sidebar → "Build", or terminal: `pio run`
- Upload: PlatformIO sidebar → "Upload", or terminal: `pio run -t upload`
- Monitor: PlatformIO sidebar → "Monitor", or terminal: `pio device monitor`

Build errors land in the Problems panel. Compile-time errors with line numbers work the way you'd expect from any C/C++ toolchain.

### 3. Commit

When you've made progress worth saving (a working feature, a partial step you don't want to lose, a bug fix), commit:

```bash
git status                          # see what's changed
git diff                            # see the actual changes
git add firmware/src/main.cpp       # stage specific files
# or
git add .                           # stage everything
git commit -m "Initial blinky working on dev kit"
```

A good commit is **one logical change**. Not "today's work" — that's too big. Aim for commits you could describe in one short sentence. "Add IMU SPI initialization." "Fix sample rate calculation off-by-one." "Move log buffer to PSRAM."

### 4. Push (end of session, or any time)

```bash
git push
```

This sends your commits to GitHub. Now they exist in two places — your laptop and GitHub's servers. GitHub is your offsite backup. If your laptop dies, you re-clone and continue. This is one of the under-appreciated benefits of git for solo work: it's a backup system that happens to also be a versioning system.

### How often to commit

More than feels natural. Software people commit shockingly often when you watch them — sometimes every 15 minutes during active work. The reason: each commit is an undo point. The cost of an unnecessary commit is zero; the cost of losing four hours of work because you didn't commit is four hours.

Rough heuristic: if you'd be annoyed losing what you just did, commit it.

---

## When you mess up: recovery

You will mess up. Recovery is the scariest part of git for newcomers, so let's name the common cases.

### "I broke something and want to go back to my last commit"

```bash
git diff                  # confirm what's changed
git checkout -- .         # discard all uncommitted changes
```

Your working directory now matches the last commit. The changes are gone — git is doing exactly what you told it.

### "I committed something I didn't mean to commit"

If you haven't pushed yet:

```bash
git reset --soft HEAD~1   # undo the last commit, keep the changes staged
# or
git reset --hard HEAD~1   # undo the last commit AND throw away the changes
```

If you have pushed, the conservative move is to make a new commit that fixes the problem. Rewriting pushed history is possible but adds complexity you don't need yet.

### "I want to see what a file looked like last week"

```bash
git log firmware/src/main.cpp           # commits that touched this file
git show <commit-hash>:firmware/src/main.cpp   # the file at that commit
```

### "I want to try something risky without disturbing the working version"

This is what branches are for. You don't strictly need them solo, but they're handy for experiments:

```bash
git checkout -b experimental-fifo-reads    # create + switch to new branch
# ... edit, commit, edit, commit ...
git checkout main                          # switch back; experimental work is preserved on its branch
git merge experimental-fifo-reads          # if the experiment worked, fold it in
# or
git branch -D experimental-fifo-reads      # if it didn't, delete it
```

For solo work, you can ignore branches entirely until you have a reason to want one. Don't overcomplicate.

---

## Commit message hygiene

The commit message is what future-you reads when you're trying to figure out why something is the way it is. Treat it accordingly.

- First line: short summary, imperative mood ("Add SPI bus init", not "Added" or "Adds")
- Under 72 characters for the first line if you can
- If the change needs explanation, blank line, then a paragraph

Examples of good commits:

```
Initial blinky on dev kit

Verifies the toolchain end-to-end. Onboard LED on GPIO 48,
serial at 115200. No peripherals yet.
```

```
Switch IMU FIFO to watermark interrupt
```

```
Bump SdFat to 2.2.2 to fix sustained-write hang

Saw 2-3 second stalls during 10+ minute sessions on the
older library. New version uses an internal buffer that
absorbs the worst of the SD-card housekeeping latency.
```

Examples of unhelpful commits:

```
update
fix
working
asdf
WIP
```

You'll write some of those anyway. That's fine. Just notice when you're doing it and try to do better next time.

---

## .gitignore decoded

Worth understanding what each line in `.gitignore` is for, because eventually you'll add to it.

| Pattern | Why it's ignored |
|---|---|
| `.pio/` | PlatformIO build output. Regenerated from source every build. Hundreds of MB. |
| `*.elf`, `*.bin` | Compiled binaries. Same reason. |
| `__pycache__/` | Python bytecode cache. Regenerated on every Python run. |
| `*.pyc` | Same. |
| `.ipynb_checkpoints/` | Jupyter autosaves. Pollute git diffs. |
| `.venv/` | Python virtual environments. Reproducible from `requirements.txt`. |
| `sessions/` | Your water-test logs. Not source code, often large, sometimes private. |
| `.DS_Store`, `Thumbs.db` | OS metadata. Useless to anyone. |
| `*.swp`, `*~` | Editor temp files. |
| `.env`, `secrets.h` | API keys, passwords, anything you don't want public. **Critical** even on a private repo. |

Rule of thumb: if a file is **generated** (build output, cache, log) or **secret** (credentials), it doesn't belong in git. If it's **source** (code, configuration, documentation), it does.

---

## Where to go from here

You don't need any of this yet, but it's the natural next layer when the project gets bigger:

- **Branches** for features you don't want to merge until they're done
- **Pull requests** when you have a collaborator (Josh? Ray?) and want their review before merging
- **Tags** for marking firmware versions you flashed to specific units (`v0.1`, `v0.2`)
- **Continuous integration** (GitHub Actions) for auto-running builds on every push, so you find out something broke without having to remember to test
- **Semantic versioning** for tagged releases (`v1.2.3` = major.minor.patch)

Skip all of that for now. The core loop — pull, edit, build, commit, push — is 95% of the value. The rest is polish you add when you feel the lack of it.

---

## Common stumbles

A few things that bite people in their first month.

**"My push is rejected because the remote has changes."** You committed locally, but someone (or you, on another machine) pushed to GitHub first. Fix: `git pull` to merge their changes in, resolve any conflicts, then `git push`.

**"I committed something huge by accident."** You ran `git add .` and accidentally pulled in a 500 MB session log. Before you push: `git reset HEAD~1` to undo the commit, add the big thing to `.gitignore`, recommit. After you push: it's harder; ask for help. The git internals remember the file forever once it's in.

**"PlatformIO won't find my board."** USB driver issue, almost always. Mac and Linux usually work out of the box; Windows often needs a CP210x or CH340 driver depending on the dev kit's USB-to-serial chip. The ESP32-S3-DevKitC-1 uses native USB so this is less of an issue, but check Device Manager.

**"My code compiled but the board behaves weirdly after upload."** Hold the BOOT button while clicking Upload, or before plugging in. The S3 sometimes needs help getting into download mode, especially with USB-CDC enabled.

**"I added a library to `lib_deps` and it broke everything."** Library version conflict — another library depends on a different version of a shared dependency. Read the error, pin the conflicting library to a specific version with `@^x.y.z` syntax in `platformio.ini`.

---

## A worked example: from zero to first commit

Putting it all together. After installs are done:

```bash
# Get the code on disk
cd ~/Projects
git clone git@github.com:yourusername/kikaha-coach.git
cd kikaha-coach

# Set up the structure
mkdir -p firmware/src firmware/include tools analysis docs sessions

# Create the files (paste the contents from this guide)
# ... use VSCode or your editor of choice ...

# Verify the build works
pio run

# If it built, commit
git add .
git status                # confirm what's staged
git commit -m "Initial project skeleton with blinky"
git push

# Done. You have a working, version-controlled, buildable project.
```

The first time you do this, set aside two hours and don't fight if something doesn't work — google the error message, it's almost certainly someone else's stumble too. After this first run-through, the muscle memory takes over and the whole loop becomes invisible.
