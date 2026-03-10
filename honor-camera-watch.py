#!/usr/bin/env python3
import os
import subprocess
import threading
import time

import pyudev
from evdev import InputDevice, ecodes

# ---- Config (aus deinen Logs) ----
USB_VENDOR_ID = "3277"
USB_MODEL_ID = "00a8"

# Storage-slot key events (aus evtest)
KEY_STORAGE_REMOVED = 587  # KEY_CAMERA_ACCESS_ENABLE -> aus Slot heraus holen
KEY_STORAGE_INSERTED = 588 # KEY_CAMERA_ACCESS_DISABLE -> in Slot hinein stecken

# Optional: Wenn du das noch nutzen willst (Privacy-Taste)
KEY_PRIVACY_TOGGLE = 589   # KEY_CAMERA_ACCESS_TOGGLE

# Du hast event11 genannt. Optional später automatisieren via by-path/by-id.
INPUT_EVENT_DEV = "/dev/input/event11"

APP_NAME = "Honor Camera"


def notify(summary: str, transient: bool = True, replace_id: int | None = None) -> int | None:
    """
    Uses notify-send.
    - transient=True: kurzlebig (Windows 'Attached')
    - transient=False: "persistent" (so persistent wie der DE es zulässt)
    - replace_id: ersetzt eine vorhandene Notification (GNOME/KDE unterstützen das i.d.R.)
    Returns notification id if possible (notify-send -p).
    """
    cmd = ["notify-send", "-a", APP_NAME]

    # "persistenter" Versuch: keine echte Garantie, hängt vom Notification-Server ab.
    # Viele Server ignorieren -t 0; trotzdem: besser als nichts.
    if transient:
        cmd += ["-t", "3500"]
    else:
        cmd += ["-t", "8000"]

    if replace_id is not None:
        cmd += ["-r", str(replace_id)]

    # -p: print id (nicht überall vorhanden, aber bei libnotify üblich)
    cmd += ["-p", summary]

    try:
        out = subprocess.check_output(cmd, text=True).strip()
        return int(out) if out.isdigit() else None
    except Exception:
        # Fallback ohne -p
        try:
            subprocess.Popen(["notify-send", "-a", APP_NAME, summary])
        except Exception:
            pass
        return None


class State:
    def __init__(self):
        self.usb_present = False
        self.storage_present = True  # Annahme: beim Start steckt sie oft drin; wird korrigiert sobald Key kommt
        self.ejected_nid = None      # Notification-id für "Camera Ejected" zum Ersetzen/Ausblenden


state = State()


def show_ejected_persistent():
    # Persistent "Camera Ejected" (Windows 1.a)
    state.ejected_nid = notify("Camera Ejected", transient=False, replace_id=state.ejected_nid)


def hide_ejected():
    # Es gibt kein standardisiertes "close notification" über notify-send.
    # Aber wir können sie "ersetzen" durch eine kurze neutrale Info oder leere ersetzen.
    # Viele Server akzeptieren eine Ersetzung mit kurzer Laufzeit.
    if state.ejected_nid is not None:
        notify(" ", transient=True, replace_id=state.ejected_nid)
        state.ejected_nid = None


def on_storage_removed():
    state.storage_present = False
    # Nur anzeigen, wenn nicht gerade attached.
    if not state.usb_present:
        show_ejected_persistent()


def on_storage_inserted():
    state.storage_present = True
    # Wenn sie zurück im Storage ist, macht Windows mWn keinen extra Toast.
    # Wir können "Ejected" ausblenden, weil sie wieder verstaut ist.
    hide_ejected()


def on_usb_attached():
    state.usb_present = True
    # Windows 2.a: ejected ausblenden
    hide_ejected()
    # Windows 2.c: Attached kurz
    notify("Attached", transient=True)


def on_usb_disconnected():
    state.usb_present = False
    # Windows 3.a: disconnected toast
    notify("Camera disconnected", transient=True)
    # Optional: wenn sie nicht im Storage ist -> ejected wieder anzeigen
    if not state.storage_present:
        show_ejected_persistent()


def usb_watch_loop():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="usb")
    for device in iter(monitor.poll, None):
        try:
            if device.action not in ("add", "remove"):
                continue
            # Match genau dein Device
            if device.get("ID_VENDOR_ID") != USB_VENDOR_ID:
                continue
            if device.get("ID_MODEL_ID") != USB_MODEL_ID:
                continue

            if device.action == "add":
                on_usb_attached()
            elif device.action == "remove":
                on_usb_disconnected()
        except Exception:
            continue


def input_watch_loop():
    dev = InputDevice(INPUT_EVENT_DEV)
    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY:
            continue
        if event.value != 1:  # nur "press"
            continue

        if event.code == KEY_STORAGE_REMOVED:
            on_storage_removed()
        elif event.code == KEY_STORAGE_INSERTED:
            on_storage_inserted()
        elif event.code == KEY_PRIVACY_TOGGLE:
            # erstmal ignorieren oder optional debug:
            pass


def main():
    # Start threads
    t1 = threading.Thread(target=usb_watch_loop, daemon=True)
    t2 = threading.Thread(target=input_watch_loop, daemon=True)
    t1.start()
    t2.start()

    # Keep alive
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
