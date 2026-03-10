#!/usr/bin/env python3
import glob
import subprocess
import threading
import time
import sys

import pyudev
from evdev import InputDevice, ecodes

USB_VENDOR_ID = "3277"
USB_MODEL_ID = "00a8"

KEY_STORAGE_REMOVED = 587   # KEY_CAMERA_ACCESS_ENABLE
KEY_STORAGE_INSERTED = 588  # KEY_CAMERA_ACCESS_DISABLE
KEY_PRIVACY_TOGGLE = 589

HOTKEY_DEVICE_NAME = "Huawei WMI hotkeys"
APP_NAME = "Honor Camera"

def log(msg: str):
    print(msg, flush=True)

class State:
    def __init__(self):
        self.usb_present = False
        self.storage_present = True
        self.ejected_nid = None

state = State()

def notify(summary: str, transient: bool = True, replace_id=None):
    cmd = ["notify-send", "-a", APP_NAME]
    cmd += ["-t", "3500" if transient else "0"]
    if replace_id is not None:
        cmd += ["-r", str(replace_id)]
    cmd += ["-p", summary]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        return int(out) if out.isdigit() else replace_id
    except Exception as e:
        log(f"notify failed: {e}")
        return replace_id

def show_ejected_persistent():
    log("STATE: show_ejected")
    state.ejected_nid = notify("Camera Ejected", transient=False, replace_id=state.ejected_nid)

def hide_ejected():
    log("STATE: hide_ejected")
    if state.ejected_nid is not None:
        notify(" ", transient=True, replace_id=state.ejected_nid)
        state.ejected_nid = None

def on_storage_removed():
    log("EVENT: storage_removed (587)")
    state.storage_present = False
    if not state.usb_present:
        show_ejected_persistent()

def on_storage_inserted():
    log("EVENT: storage_inserted (588)")
    state.storage_present = True
    hide_ejected()

def on_usb_attached():
    log("EVENT: usb_attached")
    state.usb_present = True
    hide_ejected()
    notify("Attached", transient=True)

def on_usb_disconnected():
    log("EVENT: usb_disconnected")
    state.usb_present = False
    notify("Camera disconnected", transient=True)
    if not state.storage_present:
        show_ejected_persistent()

def usb_watch_loop():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="usb")
    log("USB monitor started")

    for device in iter(monitor.poll, None):
        try:
            if device.action not in ("add", "remove"):
                continue
            if device.get("ID_VENDOR_ID") != USB_VENDOR_ID:
                continue
            if device.get("ID_MODEL_ID") != USB_MODEL_ID:
                continue

            log(f"USB match: action={device.action} devpath={device.device_path}")
            if device.action == "add":
                on_usb_attached()
            else:
                on_usb_disconnected()
        except Exception as e:
            log(f"USB loop error: {e}")

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
            log("Input device not found yet; retrying...")
            time.sleep(1.0)
            continue

        log(f"Input monitor started on {path} ({HOTKEY_DEVICE_NAME})")
        try:
            dev = InputDevice(path)
            for event in dev.read_loop():
                if event.type != ecodes.EV_KEY:
                    continue
                if event.value != 1:  # press only
                    continue

                log(f"KEY press: code={event.code}")
                if event.code == KEY_STORAGE_REMOVED:
                    on_storage_removed()
                elif event.code == KEY_STORAGE_INSERTED:
                    on_storage_inserted()
                elif event.code == KEY_PRIVACY_TOGGLE:
                    log("EVENT: privacy_toggle (589) (ignored)")
        except PermissionError as e:
            log(f"PermissionError reading {path}: {e}")
            time.sleep(2.0)
        except OSError as e:
            # device disappeared / "connection closed"
            log(f"Input device error (will retry): {e}")
            time.sleep(0.2)

def main():
    t1 = threading.Thread(target=usb_watch_loop, daemon=True)
    t2 = threading.Thread(target=input_watch_loop, daemon=True)
    t1.start()
    t2.start()
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
