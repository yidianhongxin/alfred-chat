#!/usr/bin/env python3
"""Add Cmd+3 hotkey to open the most recent Alfred Chat conversation."""

import plistlib
import uuid
from pathlib import Path

PLIST_PATH = Path(__file__).resolve().parent.parent / "Workflow" / "info.plist"

HOTKEY_UID = "C3A9D1E2-4F5B-6A7C-8D9E-0F1A2B3C4D5E"
RECENT_SCRIPT_UID = "D4B0E2F3-5A6C-7B8D-9E0F-1A2B3C4D5E6F"
VIEW_CHAT_UID = "2345B220-18B0-4F70-9DD7-B7A20763FFBC"


def make_hotkey_object():
    return {
        "config": {
            "hotkey": 20,
            "hotmod": 1048576,
            "leftcursor": False,
            "donotshowmodhint": False,
            "hotkeyLabel": "Open recent chat",
        },
        "type": "alfred.workflow.trigger.hotkey",
        "uid": HOTKEY_UID,
        "version": 1,
    }


def make_recent_script_object():
    return {
        "config": {
            "concurrently": False,
            "escaping": 102,
            "script": "",
            "scriptargtype": 0,
            "scriptfile": "recent_chat.js",
            "type": 7,
        },
        "type": "alfred.workflow.action.script",
        "uid": RECENT_SCRIPT_UID,
        "version": 2,
    }


def make_set_vars_object():
    return {
        "config": {
            "argument": "",
            "passthroughargument": False,
            "variables": {
                "chat_history_save": "1",
                "replace_with_chat": "{query}",
            },
        },
        "type": "alfred.workflow.utility.argument",
        "uid": SET_VARS_UID,
        "version": 1,
    }


def main():
    with PLIST_PATH.open("rb") as handle:
        data = plistlib.load(handle)

    uids = {obj["uid"] for obj in data["objects"]}
    for obj in [make_hotkey_object(), make_recent_script_object()]:
        if obj["uid"] not in uids:
            data["objects"].append(obj)

    data["connections"][HOTKEY_UID] = [{
        "destinationuid": RECENT_SCRIPT_UID,
        "modifiers": 0,
        "modifiersubtext": "",
        "vitoclose": False,
    }]
    data["connections"][RECENT_SCRIPT_UID] = [{
        "destinationuid": VIEW_CHAT_UID,
        "modifiers": 0,
        "modifiersubtext": "",
        "vitoclose": False,
    }]

    data.setdefault("uidata", {})
    data["uidata"][HOTKEY_UID] = {"xpos": 65.0, "ypos": 540.0, "colorindex": 4}
    data["uidata"][RECENT_SCRIPT_UID] = {"xpos": 280.0, "ypos": 540.0}
    data["uidata"][SET_VARS_UID] = {"xpos": 495.0, "ypos": 540.0}

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    print("Added Cmd+3 hotkey for recent chat")


if __name__ == "__main__":
    main()
