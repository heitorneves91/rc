"""Centralized application configuration.

A single `config` object holds every tunable parameter for the vehicle
(movement, camera, ground-station link, pigpio connection, logging).

On import the configuration is loaded from `.config.json` if that file
exists next to this module; any keys missing from the file fall back to the
defaults defined here, so the format can grow over time without breaking
older config files.

Use `config.update(...)` to change values at runtime — it applies the change
in-memory and immediately writes the whole configuration back to disk.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any


# `.config.json` lives next to this module so the path is stable regardless
# of the current working directory of whichever service imported it.
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".config.json")


@dataclass
class MovementConfig:
    rl_motor_gpio: int = 19
    steering_gpio: int = 18

    # Seconds to hold the minimum signal so the ESC can arm on startup.
    arm_delay_s: float = 2.0

    # Failsafe: if no drive command arrives within this window (seconds), the
    # movement watchdog cuts the throttle. Enforced by movement_service itself,
    # independent of which link delivered (or stopped delivering) commands.
    command_timeout_s: float = 1.0


@dataclass
class CameraConfig:
    width: int = 1280
    height: int = 720
    framerate: int = 30
    # UDP port the camera stream is sent to on the ground-station host.
    stream_port: int = 9999


@dataclass
class GroundStationConfig:
    listen_port: int = 8888
    # How often telemetry is sent to the ground station once its address is
    # known (seconds).
    telemetry_interval_s: float = 0.25


@dataclass
class Configuration:
    """Top-level configuration aggregating every service's settings."""

    movement: MovementConfig = field(default_factory=MovementConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    ground_station: GroundStationConfig = field(default_factory=GroundStationConfig)

    log_level: str = "INFO"

    # Filled in by load(); not part of the serialized data.
    _path: str = field(default=CONFIG_PATH, repr=False, compare=False)

    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Configuration":
        """Build a Configuration from `path`, falling back to defaults.

        Missing file or missing keys are tolerated: anything absent keeps its
        default value.
        """
        cfg = cls()
        cfg._path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _apply(cfg, data)
        return cfg

    def to_dict(self) -> dict[str, Any]:
        """Serializable view of the configuration (excludes private fields)."""
        data = asdict(self)
        return {k: v for k, v in data.items() if not k.startswith("_")}

    def save(self) -> None:
        """Persist the current configuration to disk atomically."""
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self._path)

    def update(self, **changes: Any) -> "Configuration":
        """Apply changes and immediately persist to `.config.json`.

        Accepts top-level fields by name. Nested sections may be updated by
        passing either a section dataclass instance or a dict of partial
        values, e.g.::

            config.update(log_level="DEBUG")
            config.update(movement={"esc_gpio": 21})

        Returns self so calls can be chained.
        """
        valid = {f.name for f in fields(self) if not f.name.startswith("_")}
        for key, value in changes.items():
            if key not in valid:
                raise KeyError(f"Unknown configuration field: {key!r}")
            current = getattr(self, key)
            if is_dataclass(current) and isinstance(value, dict):
                _apply(current, value)
            else:
                setattr(self, key, value)
        self.save()
        return self


def _apply(target: Any, data: dict[str, Any]) -> None:
    """Recursively apply a dict of values onto a dataclass instance.

    Unknown keys are ignored; nested dataclasses are merged in place so a
    partial config file leaves untouched fields at their defaults.
    """
    valid = {f.name for f in fields(target)}
    for key, value in data.items():
        if key not in valid or key.startswith("_"):
            continue
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value)
        else:
            setattr(target, key, value)


# Application-wide singleton. Import this everywhere:
#     from configuration import config
config = Configuration.load()