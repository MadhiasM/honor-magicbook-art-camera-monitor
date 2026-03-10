#!/usr/bin/env python3
import glob
import subprocess
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
ICON_PATH = "/home/mathias/Dokumente/Code/Honor_Camera_Notifier/CameraIcon/"
ICON_NAME = "public_camera_filled.svg" # "BG_Circle.svg" , "kamera.png"
ICON = f"{ICON_PATH}{ICON_NAME}"

NOTIFICATION_DURATION = 3000 # Display time of notifications in milliseconds
NID = 0  # notify-send replacement id; start with 0

WARN_AFTER_SECONDS = 8.0  # debounce window
_warn_timer = None

def notify_transient(summary: str, timeout_ms: int = NOTIFICATION_DURATION):
    """
    GNOME: transient hint prevents notification from going to history / notification center.
    Uses notify-send -p to get an ID, and -r <previous_id> to replace immediately.
    This matches the behavior you quoted (NID=$(notify-send -p -r $NID ...)).
    """
    global NID

    cmd = [
        "notify-send",
        "-a", APP_NAME,
        "-t", str(timeout_ms),
        "-h", "int:transient:1", # why not -e?
        "-p",
        "-r", str(NID),       # replace previous
        #"-u", "critical",
        "-i", ICON,
        summary,
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        # notify-send -p returns the new/current id; keep it for next replace
        if out.isdigit():
            NID = int(out)
    except Exception:
        # fallback: fire-and-forget (no replacement)
        subprocess.Popen([c for c in cmd if c not in ("-p", "-r", str(NID))])

class State:
    def __init__(self):
        self.usb_present = False
        self.storage_present = None  # unknown until first key

state = State()

def find_hotkey_event_device():
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            dev = InputDevice(path)
            if dev.name == HOTKEY_DEVICE_NAME:
                return path
        except Exception:
            continue
    return None

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
                    # transient toast (nicht persistent)
                    notify_transient("Camera ejected", NOTIFICATION_DURATION)

                elif event.code == KEY_STORAGE_INSERTED:
                    state.storage_present = True # TODO: Fix
                    notify_transient("Camera inserted", NOTIFICATION_DURATION) # Stored or inserted
                    pass

        except OSError:
            # device disappeared / re-enumerated -> rescan
            time.sleep(0.2)
        except PermissionError:
            # keine Rechte -> warte, damit user/udev das fixen kann
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

        # Dedupe: nur die Capture-Node (video0) zählt
        caps = device.get("ID_V4L_CAPABILITIES", "")
        if ":capture:" not in caps:
            continue

        if action == "add":
            state.usb_present = True
            notify_transient("Camera attached", NOTIFICATION_DURATION)
        elif action == "remove":
            state.usb_present = False
            notify_transient("Camera disconnected", NOTIFICATION_DURATION) # Disconnected or detached

def _cancel_warn_timer():
    global _warn_timer
    if _warn_timer is not None:
        _warn_timer.cancel()
        _warn_timer = None

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


# --- modify event handlers accordingly ---

def on_storage_removed():
    state.storage_present = False
    notify_transient("Ejected", icon_path=ICON_EJECTED, timeout_ms=3500)
    _arm_missing_warning_timer()

def on_storage_inserted():
    state.storage_present = True
    _cancel_warn_timer()
    _clear_warning()

def on_usb_attached():
    state.usb_present = True
    _cancel_warn_timer()
    _clear_warning()
    notify_transient("Attached", icon_path=ICON_ATTACHED, timeout_ms=2500)

def on_usb_disconnected():
    state.usb_present = False
    notify_transient("Disconnected", icon_path=ICON_DISCONNECTED, timeout_ms=3500)
    _arm_missing_warning_timer()

def main():
    t1 = threading.Thread(target=input_watch_loop, daemon=True)
    t2 = threading.Thread(target=udev_watch_loop, daemon=True)
    t1.start()
    t2.start()

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
