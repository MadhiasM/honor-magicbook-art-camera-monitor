#!/usr/bin/env python3
import glob
import subprocess
import os
import threading
import time

import pyudev
from evdev import InputDevice, ecodes

USB_VENDOR_ID = "3277"
USB_MODEL_ID = "00a8"

KEY_STORAGE_REMOVED = 587   # KEY_CAMERA_ACCESS_ENABLE (aus Storage raus)
KEY_STORAGE_INSERTED = 588  # KEY_CAMERA_ACCESS_DISABLE (in Storage rein)
HOTKEY_DEVICE_NAME = "Huawei WMI hotkeys"

APP_NAME = "Honor Camera"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, "CameraIcon")
ICON_NAME = "public_camera_filled.svg" # "BG_Circle.svg" , "kamera.png"
ICON = f"{ICON_PATH}{ICON_NAME}"

NOTIFICATION_DURATION = 3000 # Display time of notifications in milliseconds

SLEEP_TIME = 3600

# Replacement IDs for notify-send (-p / -r)
NID = 0        # for transient toasts
WARN_NID = 0   # for persistent warning

WARN_AFTER_SECONDS = 8.0 # Debounce window
WARNING_CLOSE_GRACE_MS = 120  # small delay to avoid GNOME swallowing next popup
_warn_timer = None
warn_active = False

_notify_lock = threading.Lock()

class State:
    def __init__(self):
        self.usb_present = False
        self.storage_present = None  # unknown until first key

state = State()

def notify_transient(summary: str, timeout_ms: int = NOTIFICATION_DURATION):
    """
    Transient popup (should not go to notification center) and replaces previous toast immediately.
    Thread-safe: uses a lock because input + udev run in parallel threads.
    """
    global NID
    with _notify_lock:
        cmd = [
            "notify-send",
            "-a", APP_NAME,
            "-t", str(timeout_ms),
            "-h", "int:transient:1",
            "-p",
            "-r", str(NID),
            "-i", ICON,
            summary,
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        if out.isdigit():
            NID = int(out)

def _show_warning_persistent():
    """
    Persistent-ish warning. GNOME may still impose limits, but this is the best we can do via notify-send.
    Uses its own replace-id so it doesn't fight with transient toasts.
    """
    global WARN_NID, warn_active
    with _notify_lock:
        cmd = [
            "notify-send",
            "-a", APP_NAME,
            "-u", "critical",
            "-t", "0",
            "-h", "int:transient:0",
            "-p",
            "-r", str(WARN_NID),
            "-i", ICON,
            "Camera missing",
            "No camera deteced",
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        if out.isdigit():
            WARN_NID = int(out)
    warn_active = True

def _cancel_warn_timer():
    global _warn_timer
    if _warn_timer is not None:
        _warn_timer.cancel()
        _warn_timer = None

def _close_notification(nid: int):
    # Best-effort: close via DBus. Works in GNOME.
    subprocess.Popen([
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.Notifications",
        "--object-path", "/org/freedesktop/Notifications",
        "--method", "org.freedesktop.Notifications.CloseNotification",
        str(nid),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _clear_warning():
    global WARN_NID, warn_active
    if not warn_active:
        return
    # close the warning immediately (no blank replacement)
    _close_notification(WARN_NID)
    warn_active = False

def clear_warning_and_toast(summary: str, timeout_ms: int = NOTIFICATION_DURATION):
    """
    Atomically: close warning (if active) and then show a transient toast.
    Prevents the "inserted" popup from being swallowed / going only to notification center.
    """
    global NID, WARN_NID, warn_active

    with _notify_lock:
        if warn_active:
            _close_notification(WARN_NID)
            warn_active = False
            time.sleep(WARNING_CLOSE_GRACE_MS / 1000.0)

        cmd = [
            "notify-send",
            "-a", APP_NAME,
            "-t", str(timeout_ms),
            "-h", "int:transient:1",
            "-p",
            "-r", str(NID),
            "-i", ICON,
            summary,
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        if out.isdigit():
            NID = int(out)

def _arm_missing_warning_timer():
    """
    Arm the missing-camera alarm after an "Ejected" or "Disconnected" event.
    It will only fire if, within WARN_AFTER_SECONDS, we do NOT see:
      a) USB attached, or
      b) Storage inserted.
    """
    global _warn_timer
    _cancel_warn_timer()
    _warn_timer = threading.Timer(WARN_AFTER_SECONDS, _warn_fire_if_still_missing)
    _warn_timer.daemon = True
    _warn_timer.start()


def _warn_fire_if_still_missing():
    # Only alarm if still neither attached nor inserted
    if state.usb_present is True:
        return
    if state.storage_present is True:
        return
    # If storage_present is None (unknown), be conservative and don't alarm
    if state.storage_present is None:
        return

    _show_warning_persistent()



def find_hotkey_event_device():
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice(path)
            if dev.name == HOTKEY_DEVICE_NAME:
                return path
        except Exception:
            continue
    return None

def _initial_probe_usb_present():
    """
    Determine initial usb_present at startup (in case the camera is already attached
    before our udev monitor begins).
    """
    context = pyudev.Context()
    for dev in context.list_devices(subsystem="video4linux"):
        if dev.get("ID_VENDOR_ID") != USB_VENDOR_ID:
            continue
        if dev.get("ID_MODEL_ID") != USB_MODEL_ID:
            continue
        caps = dev.get("ID_V4L_CAPABILITIES", "")
        if ":capture:" not in caps:
            continue
        return True
    return False

def input_watch_loop():
    while True:
        path = find_hotkey_event_device()
        if not path:
            time.sleep(1.0)
            continue

        try:
            dev = InputDevice(path)
            for event in dev.read_loop():
                if event.type != ecodes.EV_KEY or event.value != 1:
                    continue

                if event.code == KEY_STORAGE_REMOVED:
                    state.storage_present = False
                    notify_transient("Camera ejected")
                    _arm_missing_warning_timer()

                elif event.code == KEY_STORAGE_INSERTED:
                    state.storage_present = True
                    _cancel_warn_timer()
                    clear_warning_and_toast("Camera inserted", NOTIFICATION_DURATION)

        except OSError:
            # device disappeared / re-enumerated -> rescan
            time.sleep(0.2)
        except PermissionError:
            time.sleep(2.0)

def udev_watch_loop():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="video4linux")

    for device in iter(monitor.poll, None):
        action = device.action
        if action not in ("add", "remove"):
            continue

        if device.get("ID_VENDOR_ID") != USB_VENDOR_ID:
            continue
        if device.get("ID_MODEL_ID") != USB_MODEL_ID:
            continue

        # Dedupe: only the capture node counts (e.g. video0)
        caps = device.get("ID_V4L_CAPABILITIES", "")
        if ":capture:" not in caps:
            continue

        if action == "add":
            state.usb_present = True
            _cancel_warn_timer()
            clear_warning_and_toast("Camera attached", NOTIFICATION_DURATION)

        elif action == "remove":
            state.usb_present = False

            # Inference: if we don't know storage state yet, a USB disconnect implies it's not in storage
            # This will alow for the warning to be displayed if it is not inserted into storage or attached to USB again
            if state.storage_present is None:
                state.storage_present = False

            notify_transient("Camera disconnected") # Disconnected or detached
            _arm_missing_warning_timer()

def main():
    # USB state can be detected at startup due to presence of usb device.
    # Storage state cannot be detected since it is
    state.usb_present = _initial_probe_usb_present()
    t1 = threading.Thread(target=input_watch_loop, daemon=True)
    t2 = threading.Thread(target=udev_watch_loop, daemon=True)
    t1.start()
    t2.start()

    while True:
        time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    main()
