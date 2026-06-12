"""Camera service: streams H.264 video to the ground station over UDP.

Touching the camera from Python would be too slow for live video, so we don't:
we spawn ``rpicam-vid`` and let it capture, encode and push the UDP stream on
its own. This module only manages the lifetime of that subprocess — start it
(pointed at the ground station's host) and kill it on request.

The equivalent command line is::

    rpicam-vid -t 0 --inline --codec h264 \
      --width <w> --height <h> --framerate <f> \
      -o udp://<host>:<port>
"""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

from configuration import config


# Guards `_process` so START/STOP from the receive loop can't race.
_lock = threading.Lock()
_process: Optional[subprocess.Popen] = None


def start(host: str, width: int, height: int, framerate: int) -> None:
    """(Re)start the video stream to ``host`` on the configured UDP port.

    Any existing stream is stopped first, so this is safe to call repeatedly
    (e.g. when the resolution changes).
    """
    global _process
    with _lock:
        _stop_locked()
        cmd = [
            "rpicam-vid",
            "-t", "0",
            "--inline",
            "--codec", "h264",
            "--width", str(width),
            "--height", str(height),
            "--framerate", str(framerate),
            "-o", f"udp://{host}:{config.camera.stream_port}",
        ]
        print(f"camera_service: starting stream -> {' '.join(cmd)}")
        _process = subprocess.Popen(cmd)


def stop() -> None:
    """Kill the streaming subprocess if it is running. Safe to call anytime."""
    with _lock:
        _stop_locked()


def _stop_locked() -> None:
    """Terminate the subprocess; caller must hold `_lock`."""
    global _process
    if _process is None:
        return
    if _process.poll() is None:
        print("camera_service: stopping stream")
        _process.terminate()
        try:
            _process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait()
    _process = None
