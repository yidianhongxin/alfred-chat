#!/usr/bin/env python3
"""Add dedicated history keyword to Alfred Chat workflow."""

import plistlib
import uuid
from pathlib import Path

PLIST_PATH = Path(__file__).resolve().parent.parent / "Workflow" / "info.plist"

HISTORY_SCRIPT_FILTER_UID = "B2F04B2C-63AD-4A6D-9A81-7F333D0A075A"
CHAT_KEYWORD_UID = "BF340515-39CD-47C9-965D-B1631A3BF45F"
NEW_KEYWORD_UID = "E8F4A2B1-6C3D-4E5F-9012-3456789ABCDE"

UPDATED_HISTORY_SCRIPT = """function envVar(varName) {
  return $.NSProcessInfo
    .processInfo
    .environment
    .objectForKey(varName).js
}

function dirContents(path) {
  return $.NSFileManager.defaultManager.contentsOfDirectoryAtURLIncludingPropertiesForKeysOptionsError(
    $.NSURL.fileURLWithPath(path), undefined, $.NSDirectoryEnumerationSkipsHiddenFiles, undefined)
    .js.map(p => p.path.js).sort()
}

function parseSession(data) {
  if (Array.isArray(data)) return { title: null, messages: data }
  if (data && Array.isArray(data.messages)) return { title: data.title || null, messages: data.messages }
  return { title: null, messages: [] }
}

function readSession(path) {
  const chatString = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, undefined).js
  return parseSession(JSON.parse(chatString))
}

function trashChat(path) {
  const fileURL = $.NSURL.fileURLWithPath(path)
  $.NSFileManager.defaultManager.trashItemAtURLResultingItemURLError(fileURL, undefined, undefined)
}

function sessionItem(file, session, badge) {
  const firstQuestion = session.messages.find(item => item["role"] === "user")?.["content"]
  const lastQuestion = session.messages.toReversed().find(item => item["role"] === "user")?.["content"]
  const displayTitle = session.title || firstQuestion

  if (!displayTitle) return null

  const prefix = badge ? `${badge} ` : ""
  return {
    type: "file",
    title: `${prefix}${displayTitle}`,
    subtitle: lastQuestion,
    match: `${displayTitle} ${lastQuestion || ""} ${firstQuestion || ""} ${badge || ""}`,
    arg: file
  }
}

function noHistories() {
  return JSON.stringify({ items: [{
    title: "No Chat Histories Found",
    subtitle: "Start chatting, then press ⌘↩ to archive conversations",
    valid: false
  }]})
}

function run() {
  const dataDir = envVar("alfred_workflow_data")
  const currentChat = `${dataDir}/chat.json`
  const archiveDir = `${dataDir}/archive`
  const sfItems = []

  if ($.NSFileManager.defaultManager.fileExistsAtPath(currentChat)) {
    const currentSession = readSession(currentChat)
    if (currentSession.messages.length > 0) {
      const currentItem = sessionItem(currentChat, currentSession, "Current")
      if (currentItem) sfItems.push(currentItem)
    }
  }

  if ($.NSFileManager.defaultManager.fileExistsAtPath(archiveDir)) {
    dirContents(archiveDir)
      .filter(file => file.endsWith(".json"))
      .toReversed()
      .forEach(file => {
        const session = readSession(file)
        const firstQuestion = session.messages.find(item => item["role"] === "user")?.["content"]
        const displayTitle = session.title || firstQuestion

        if (!displayTitle) {
          trashChat(file)
          return
        }

        const item = sessionItem(file, session, null)
        if (item) sfItems.push(item)
      })
  }

  if (sfItems.length === 0) return noHistories()

  return JSON.stringify({ items: sfItems })
}"""


def make_history_keyword_object():
    return {
        "config": {
            "argumenttype": 1,
            "keyword": "{var:history_keyword}",
            "skipuniversalaction": True,
            "subtext": "↩ Load chat · Type to filter",
            "text": "Recent Chats",
            "withspace": True,
        },
        "type": "alfred.workflow.input.keyword",
        "uid": NEW_KEYWORD_UID,
        "version": 1,
    }


def make_history_keyword_config():
    return {
        "config": {
            "default": "rename",
            "placeholder": "",
            "required": False,
            "trim": True,
        },
        "description": "Keyword to browse recent and archived chats.",
        "label": "History Keyword",
        "type": "textfield",
        "variable": "history_keyword",
    }


def main():
    with PLIST_PATH.open("rb") as handle:
        data = plistlib.load(handle)

    uids = {obj["uid"] for obj in data["objects"]}
    if NEW_KEYWORD_UID not in uids:
        data["objects"].append(make_history_keyword_object())

    data["connections"][NEW_KEYWORD_UID] = [{
        "destinationuid": HISTORY_SCRIPT_FILTER_UID,
        "modifiers": 0,
        "modifiersubtext": "",
        "vitoclose": True,
    }]

    data["uidata"][NEW_KEYWORD_UID] = {"xpos": 65.0, "ypos": 460.0, "colorindex": 5}

    for obj in data["objects"]:
        if obj.get("uid") == CHAT_KEYWORD_UID:
            obj["config"]["subtext"] = (
                "↩ Continue chat · ⌘↩ New chat · "
                "{var:history_keyword} for history"
            )
        if obj.get("uid") == HISTORY_SCRIPT_FILTER_UID:
            obj["config"]["script"] = UPDATED_HISTORY_SCRIPT
            obj["config"]["title"] = "Recent Chats"
        if obj.get("uid") == "F87E8DE0-4373-4E35-B112-2E68DC5B10E8":
            script = obj["config"]["script"]
            old_block = """// Main
const currentChat = `${envVar("alfred_workflow_data")}/chat.json`
const replacementChat = envVar("replace_with_chat")
const archiveDir = `${envVar("alfred_workflow_data")}/archive`
const archivedChat = `${archiveDir}/${currentYear}.${currentMonth}.${currentDay}.${currentHour}.${currentMinute}.${currentSecond}-${uid}.json`

makeDir(archiveDir)
mv(currentChat, archivedChat)

if (replacementChat) {
  mv(replacementChat, currentChat)
} else {
  writeFile(currentChat, "[]")
}"""
            new_block = """// Main
const currentChat = `${envVar("alfred_workflow_data")}/chat.json`
const replacementChat = envVar("replace_with_chat")

if (replacementChat && replacementChat === currentChat) {
  // Already viewing this session
} else {
  const archiveDir = `${envVar("alfred_workflow_data")}/archive`
  const archivedChat = `${archiveDir}/${currentYear}.${currentMonth}.${currentDay}.${currentHour}.${currentMinute}.${currentSecond}-${uid}.json`

  makeDir(archiveDir)
  mv(currentChat, archivedChat)

  if (replacementChat) {
    mv(replacementChat, currentChat)
  } else {
    writeFile(currentChat, "[]")
  }
}"""
            if old_block in script:
                obj["config"]["script"] = script.replace(old_block, new_block)

    configs = data.get("userconfigurationconfig", [])
    if not any(item.get("variable") == "history_keyword" for item in configs):
        insert_at = next(
            (index for index, item in enumerate(configs) if item.get("variable") == "chat_keyword"),
            0,
        ) + 1
        configs.insert(insert_at, make_history_keyword_config())
    data["userconfigurationconfig"] = configs

    readme = data.get("readme", "")
    old_history = "View Chat History with ⌥↩ on the `chat` keyword."
    new_history = (
        "Browse recent chats with the `recent` keyword (configurable as **History Keyword**). "
        "You can also use ⌥↩ on the `chat` keyword."
    )
    if old_history in readme:
        data["readme"] = readme.replace(old_history, new_history)

    data["version"] = "1.2.0"

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    print("Added history keyword (default: recent)")


if __name__ == "__main__":
    main()
