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

def notify_transient(summary: str, timeout_ms: int = 3000):
    """
    GNOME: transient hint sorgt i.d.R. dafür, dass es nicht in die History wandert.
    """
    cmd = [
        "notify-send",
        "-a", APP_NAME,
        "-t", str(timeout_ms),
        "-h", "int:transient:1",
        summary,
    ]
    # best effort
    subprocess.Popen(cmd)

class State:
    def __init__(self):
        self.usb_present = False
        self.storage_present = None  # unknown until first key

state = State()

def find_hotkey_event_device():
    # eventX kann wechseln -> per Name suchen
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
                    # jedes Mal transient toast (nicht persistent)
                    notify_transient("Camera Ejected", 3500)

                elif event.code == KEY_STORAGE_INSERTED:
                    state.storage_present = True
                    # optional (wenn du willst):
                    # notify_transient("Camera Stored", 2000)
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

    # Wir hören auf video4linux, weil remove dort sehr zuverlässig kommt
    monitor.filter_by(subsystem="video4linux")

    for device in iter(monitor.poll, None):
        action = device.action
        if action not in ("add", "remove"):
            continue

        # Die udev-properties bei video4linux enthalten bei dir ID_VENDOR_ID/ID_MODEL_ID
        if device.get("ID_VENDOR_ID") != USB_VENDOR_ID:
            continue
        if device.get("ID_MODEL_ID") != USB_MODEL_ID:
            continue

        if action == "add":
            state.usb_present = True
            notify_transient("Attached", 2500)

        elif action == "remove":
            state.usb_present = False
            notify_transient("Camera disconnected", 3500)

def main():
    t1 = threading.Thread(target=input_watch_loop, daemon=True)
    t2 = threading.Thread(target=udev_watch_loop, daemon=True)
    t1.start()
    t2.start()

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
