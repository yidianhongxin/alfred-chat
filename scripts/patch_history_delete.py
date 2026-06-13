#!/usr/bin/env python3
"""Add Cmd+Return delete action to history Script Filter."""

import plistlib
from pathlib import Path

PLIST_PATH = Path(__file__).resolve().parent.parent / "Workflow" / "info.plist"

HISTORY_SF_UID = "B2F04B2C-63AD-4A6D-9A81-7F333D0A075A"
DELETE_SCRIPT_UID = "F1A2B3C4-D5E6-4789-A012-3456789FEDCB"

DELETE_SCRIPT = """function envVar(varName) {
  return $.NSProcessInfo
    .processInfo
    .environment
    .objectForKey(varName).js
}

function writeFile(path, text) {
  $(text).writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, undefined)
}

function trashFile(path) {
  const fileURL = $.NSURL.fileURLWithPath(path)
  $.NSFileManager.defaultManager.trashItemAtURLResultingItemURLError(fileURL, undefined, undefined)
}

function run(argv) {
  const targetPath = argv[0]
  const currentChat = `${envVar("alfred_workflow_data")}/chat.json`

  if (!targetPath || targetPath.length === 0) return

  if (targetPath === currentChat) {
    writeFile(currentChat, "[]")
    return
  }

  if ($.NSFileManager.defaultManager.fileExistsAtPath(targetPath)) {
    trashFile(targetPath)
  }
}"""


def main():
    with PLIST_PATH.open("rb") as handle:
        data = plistlib.load(handle)

    uids = {obj["uid"] for obj in data["objects"]}
    if DELETE_SCRIPT_UID not in uids:
        data["objects"].append({
            "config": {
                "concurrently": False,
                "escaping": 68,
                "script": DELETE_SCRIPT,
                "scriptargtype": 1,
                "scriptfile": "",
                "type": 7,
            },
            "type": "alfred.workflow.action.script",
            "uid": DELETE_SCRIPT_UID,
            "version": 2,
        })

    connections = data["connections"].setdefault(HISTORY_SF_UID, [])
    if not any(
        item.get("destinationuid") == DELETE_SCRIPT_UID and item.get("modifiers") == 1048576
        for item in connections
    ):
        connections.append({
            "destinationuid": DELETE_SCRIPT_UID,
            "modifiers": 1048576,
            "modifiersubtext": "Delete chat",
            "vitoclose": True,
        })

    data["uidata"][DELETE_SCRIPT_UID] = {"xpos": 1240.0, "ypos": 520.0}

    for obj in data["objects"]:
        if obj.get("uid") == HISTORY_SF_UID:
            obj["config"]["subtext"] = "↩ Load · ⌘↩ Delete · Type to filter"
        if obj.get("uid") == "E8F4A2B1-6C3D-4E5F-9012-3456789ABCDE":
            obj["config"]["subtext"] = "↩ Load · ⌘↩ Delete · Type to filter"

    readme = data.get("readme", "")
    delete_note = (
        "* &lt;kbd&gt;⌘&lt;/kbd&gt;&lt;kbd&gt;↩&lt;/kbd&gt; on a history item to delete it "
        "(Current session clears; archived chats move to Trash)."
    )
    if delete_note not in readme:
        readme = readme.replace(
            "&lt;kbd&gt;↩&lt;/kbd&gt; to archive the current chat and load the selected one.",
            "&lt;kbd&gt;↩&lt;/kbd&gt; to archive the current chat and load the selected one.\n"
            + delete_note,
        )
        data["readme"] = readme

    data["version"] = "1.2.1"

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    print("Added history delete via Cmd+Return")


if __name__ == "__main__":
    main()
