"""Ground-station link service.

Receives commands from the ground station over UDP, applies them to the
movement service, and streams telemetry back. The command-timeout failsafe
lives in ``movement_service``: this service simply feeds it commands; if they
stop arriving, the movement watchdog cuts the throttle on its own.

Wire protocol (converted from the ground station's Kotlin model). Every
message is UTF-8 text of the form ``<type>:<seq>,<field>,<field>`` where
``seq`` is a monotonically increasing counter used to drop stale/reordered
UDP packets:

    move:<seq>,<throttle>,<steering>   ground -> vehicle, drive command
    conf:<seq>,<configuration>,<value> ground -> vehicle, e.g. GROUND_HELLO
    tele:<seq>,<throttle>,<steering>   vehicle -> ground, telemetry
"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import camera_service
import movement_service
from configuration import config


class MessageType(str, Enum):
    move = "move"
    conf = "conf"
    tele = "tele"


class Configuration(str, Enum):
    GROUND_HELLO = "GROUND_HELLO"
    START_CAMERA = "START_CAMERA"
    STOP_CAMERA = "STOP_CAMERA"


@dataclass
class MoveMessage:
    seq: int
    throttle: int
    steering: int

    type = MessageType.move

    def __str__(self) -> str:
        return f"{self.type.value}:{self.seq},{self.throttle},{self.steering}"

    @classmethod
    def parse(cls, body: str) -> "MoveMessage":
        seq, throttle, steering = body.split(",")
        return cls(int(seq), int(throttle), int(steering))


@dataclass
class ConfigureMessage:
    seq: int
    configuration: Configuration
    value: Optional[str] = None

    type = MessageType.conf

    def __str__(self) -> str:
        return f"{self.type.value}:{self.seq},{self.configuration.value},{self.value}"

    @classmethod
    def parse(cls, body: str) -> "ConfigureMessage":
        parts = body.split(",")
        seq = int(parts[0])
        configuration = Configuration(parts[1])
        # The value itself may contain commas (e.g. START_CAMERA's
        # "width,height,framerate"), so keep everything after the type.
        value = ",".join(parts[2:]) if len(parts) > 2 else None
        return cls(seq, configuration, value)


@dataclass
class TelemetryMessage:
    seq: int
    throttle: int
    steering: int

    type = MessageType.tele

    def __str__(self) -> str:
        return f"{self.type.value}:{self.seq},{self.throttle},{self.steering}"


class GroundStationService:
    """Owns the UDP socket and the receive loop."""

    def __init__(self) -> None:
        self.socket: Optional[socket.socket] = None
        # Telemetry destination, learned from GROUND_HELLO (handles reconnects).
        self.ground_station_addr: Optional[tuple[str, int]] = None
        # Highest move seq seen so far; older packets are dropped as stale.
        self.last_move_seq = -1
        self.telemetry_seq = -1
        # Background telemetry sender (started once the socket is up).
        self._telemetry_stop = threading.Event()
        self._telemetry_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        # movement_service.init()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", config.ground_station.listen_port))
        print(f"ground-station-service: listening on udp/{config.ground_station.listen_port}")

        self._start_telemetry()
        self._run()

    def _run(self) -> None:
        assert self.socket is not None
        while True:
            data, addr = self.socket.recvfrom(1024)
            try:
                self._handle(data.decode("utf-8").strip(), addr)
            except (ValueError, KeyError) as exc:
                # Malformed packet: log and keep the link alive.
                print(f"ground-station-service: bad message {data!r}: {exc}")

    def _handle(self, msg: str, addr: tuple[str, int]) -> None:
        print(f"ground-station-service: {msg}")
        self.ground_station_addr = addr
        if msg.startswith("move:"):
            self._handle_move(MoveMessage.parse(msg[len("move:"):]))
        elif msg.startswith("conf:"):
            self._handle_conf(ConfigureMessage.parse(msg[len("conf:"):]), addr)
        else:
            print(f"ground-station-service: unknown message: {msg!r}")

    def _handle_move(self, msg: MoveMessage) -> None:
        # UDP can deliver out of order; ignore anything not newer than the last.
        if msg.seq <= self.last_move_seq:
            return
        self.last_move_seq = msg.seq
        movement_service.set_throttle(msg.throttle)
        movement_service.set_steering(msg.steering)

    def _handle_conf(self, msg: ConfigureMessage, addr: tuple[str, int]) -> None:
        if msg.configuration is Configuration.GROUND_HELLO:
            print(f"ground-station-service: ground station hello from {addr}")
        elif msg.configuration is Configuration.START_CAMERA:
            self._handle_start_camera(msg, addr)
        elif msg.configuration is Configuration.STOP_CAMERA:
            camera_service.stop()

    def _handle_start_camera(self, msg: ConfigureMessage, addr: tuple[str, int]) -> None:
        # Optional "width,height,framerate". Absent -> defaults. The client
        # sends either all three or none; anything else is rejected and the
        # camera is not started.
        if msg.value is None:
            width = config.camera.width
            height = config.camera.height
            framerate = config.camera.framerate
        else:
            try:
                width, height, framerate = (int(p) for p in msg.value.split(","))
            except ValueError:
                print(f"ground-station-service: bad camera params {msg.value!r}, not starting")
                return
        # Stream back to whoever asked, on the camera's UDP port.
        camera_service.start(addr[0], width, height, framerate)

    def _start_telemetry(self) -> None:
        if self._telemetry_thread is not None and self._telemetry_thread.is_alive():
            return
        self._telemetry_stop.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop, name="telemetry-sender", daemon=True
        )
        self._telemetry_thread.start()

    def _telemetry_loop(self) -> None:
        # Periodically report the vehicle's current state — but only once a
        # ground station has announced itself (GROUND_HELLO sets the address).
        while not self._telemetry_stop.wait(config.ground_station.telemetry_interval_s):
            if self.ground_station_addr is None:
                continue
            throttle, steering = movement_service.get_state()
            print(throttle, steering)
            self.send_telemetry(throttle, steering)

    def send_telemetry(self, throttle: int, steering: int) -> None:
        if self.socket is None or self.ground_station_addr is None:
            return
        self.telemetry_seq += 1
        msg = TelemetryMessage(self.telemetry_seq, throttle, steering)
        self.socket.sendto(str(msg).encode("utf-8"), self.ground_station_addr)


# Application-wide singleton.
service = GroundStationService()


def send_telemetry(throttle: int, steering: int) -> None:
    service.send_telemetry(throttle, steering)


