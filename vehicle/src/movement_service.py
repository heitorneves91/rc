"""Movement service: drives the ESC (throttle) and steering servo.

Also owns the command-timeout failsafe. A background watchdog thread watches
the time since the last drive command; if more than
``config.movement.command_timeout_s`` elapses, it cuts the throttle to the
minimum (safe) signal. This keeps the failsafe a movement concern, independent
of which link delivered the commands — any caller that stops feeding commands
will cause the vehicle to stop, with no cooperation required from the link.
"""

from configuration import config
import pigpio
import threading
import time


initialized = False
pi = pigpio.pi()

# Watchdog and current-state, guarded by `_state_lock`.
_state_lock = threading.Lock()
_last_command_monotonic = 0.0
_failsafe_active = False
# Last values written to the actuators, reported as telemetry.
_current_throttle = 0
_current_steering = 0

_watchdog_thread = None
_watchdog_stop = threading.Event()


def _apply_throttle(throttle: int) -> None:
    global _current_throttle
    pi.set_servo_pulsewidth(config.movement.rl_motor_gpio, 1000 + 10 * throttle)
    with _state_lock:
        _current_throttle = throttle


def _apply_steering(steering: int) -> None:
    global _current_steering
    pi.set_servo_pulsewidth(config.movement.steering_gpio, 1500 + 5 * steering)
    with _state_lock:
        _current_steering = steering


def get_state() -> tuple[int, int]:
    """Current (throttle, steering) as last written to the actuators."""
    
    with _state_lock:
        return _current_throttle, _current_steering


def _feed_watchdog() -> None:
    """Record that a live command was just received, clearing any failsafe."""
    global _last_command_monotonic, _failsafe_active
    with _state_lock:
        _last_command_monotonic = time.monotonic()
        _failsafe_active = False


def set_throttle(throttle: int, force=False):
    if not initialized and not force:
        print("movement_service: not yet initialized")
        return

    _feed_watchdog()
    _apply_throttle(throttle)


def set_steering(steering: int, force=False):
    if not initialized and not force:
        print("movement_service: not yet initialized")
        return

    _feed_watchdog()
    _apply_steering(steering)


def _trigger_failsafe() -> None:
    # Cut throttle directly (not via set_throttle) so the watchdog timer is not
    # fed — the vehicle stays stopped until a real command arrives. Steering is
    # left where it is.
    global _failsafe_active
    with _state_lock:
        _failsafe_active = True
    print("movement_service: command timeout — failsafe, cutting throttle")
    _apply_throttle(0)


def _watchdog_loop() -> None:
    while not _watchdog_stop.is_set():
        timeout = config.movement.command_timeout_s
        # Poll several times per timeout window so the cut is reasonably prompt.
        interval = max(0.02, timeout / 5)
        if _watchdog_stop.wait(interval):
            break

        with _state_lock:
            elapsed = time.monotonic() - _last_command_monotonic
            already_failed = _failsafe_active

        if elapsed >= timeout and not already_failed:
            _trigger_failsafe()


def _start_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_watchdog_loop, name="movement-watchdog", daemon=True
    )
    _watchdog_thread.start()


def init():
    global initialized
    initialized = False
    if not pi.connected:
        raise RuntimeError("Cannot connect to pigpiod")

    print("movement_service: minimal signal before energizing the ESC")
    set_throttle(0, force=True)
    set_steering(0, force=True)

    time.sleep(config.movement.arm_delay_s)

    initialized = True

    print("movement_service: starting command-timeout watchdog")
    _start_watchdog()
    print("movement_service: done")


def shutdown():
    """Stop the watchdog and cut the throttle. Safe to call more than once."""
    global initialized
    _watchdog_stop.set()
    if _watchdog_thread is not None:
        _watchdog_thread.join(timeout=1.0)
    initialized = False
    _apply_throttle(0)
