# CLAUDE.md

Guidance for working in this repository.

## What this is

Software for an RC vehicle that runs on a **Raspberry Pi**. Python, using
[`pigpio`](https://abyz.me.uk/rpi/pigpio/) to drive an ESC and steering servo
via timed servo pulse widths. The vehicle is operated remotely from a "ground
station" and streams camera video back.

## Architecture

The application is split into independent services under `src/`:

- `movement-service.py` — drives the ESC (throttle) and steering servo over
  pigpio servo pulse widths (1000–2000 µs, 1500 µs neutral).
- `camera-service.py` — captures and streams camera video.
- `ground-station-service.py` — link to the operator's ground station;
  receives commands and applies a command timeout failsafe.
- `configuration.py` — centralized, typed configuration (see below).
- `test.py` — standalone ESC bring-up/arming sketch (manual hardware test).

> Note: the service files are currently empty stubs; `configuration.py` is the
> first implemented module.

## Configuration

`src/configuration.py` exposes a single application-wide `config` singleton:

```python
from configuration import config

config.movement.esc_gpio          # typed nested access
config.update(log_level="DEBUG")  # persists immediately to .config.json
config.update(movement={"esc_gpio": 21})  # partial nested update
```

- Built from nested `@dataclass` sections (`pigpio`, `movement`, `camera`,
  `ground_station`) plus top-level fields like `log_level`.
- On import, loads from `.config.json` next to the module if it exists;
  missing keys fall back to defaults, so the format can evolve safely.
- `config.update(**changes)` applies changes in-memory and **immediately**
  writes the whole config back to `.config.json` (atomic temp-file + replace).
- `.config.json` is runtime state — it should not be committed.

## Development workflow — IMPORTANT

`start-pi-dev.sh` sets up live development against the physical Pi:

1. Mounts the Pi's `/home/pi/rc` over **sshfs** at `./pifs/` (the Pi is at
   `pi@192.168.0.123`).
2. Opens VS Code on `./pifs/`.
3. Every 60 s, `rsync -avz --delete` mirrors `./pifs/` → `./src/`.

**Consequence:** `./pifs/` (the Pi) is the source of truth. `./src/` is a
sync *destination* — any edit made directly in `src/` will be **overwritten**
(and `--delete` removes files not present on the Pi) on the next sync tick.
Edit code in `pifs/` (i.e. on the Pi via the mounted VS Code), not in `src/`,
while the dev sync is running.

## Conventions

- Plain Python 3 with the standard library + `pigpio`; virtualenv lives at
  `pifs/venv` on the Pi.
- Service files use a `*-service.py` naming convention.
- Comments/strings may be in Portuguese (the original `test.py` is).
