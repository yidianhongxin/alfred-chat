#!/usr/bin/env python3
"""Patch info.plist inline scripts for session title support."""

import plistlib
from pathlib import Path

PLIST_PATH = Path(__file__).resolve().parent.parent / "Workflow" / "info.plist"

COPY_LAST = """// Helpers
function envVar(varName) {
  return $.NSProcessInfo
    .processInfo
    .environment
    .objectForKey(varName).js
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

// Main
function run() {
  const chatFile = `${envVar("alfred_workflow_data")}/chat.json`
  return readSession(chatFile).messages.findLast(message => message["role"] === "assistant")["content"]
}"""

COPY_FULL = """// Helpers
function envVar(varName) {
  return $.NSProcessInfo
    .processInfo
    .environment
    .objectForKey(varName).js
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

function chatLabels() {
  const user = (envVar("chat_user_label") || "You").trim() || "You"
  const assistant = (envVar("chat_assistant_label") || "Assistant").trim() || "Assistant"
  return { user, assistant }
}

function demoteMarkdownHeadings(text, bump = 3) {
  if (!text) return text

  return text.replace(/^(#{1,6})(\\s)/gm, (_, hashes, space) => {
    const level = Math.min(hashes.length + bump, 6)
    return "#".repeat(level) + space
  })
}

function formatUserLabel(labels) {
  return `# ⊙ ${labels.user}`
}

function formatAssistantLabel(labels) {
  return `# ⊚ ${labels.assistant}`
}

function markdownChat(messages, ignoreLastInterrupted = true) {
  const labels = chatLabels()

  return messages.reduce((accumulator, current, index, allMessages) => {
    if (current["role"] === "assistant")
      return `${accumulator}${demoteMarkdownHeadings(current["content"])}\\n\\n`

    if (current["role"] === "user") {
      const userMessage = `${formatUserLabel(labels)}\\n\\n${current["content"]}\\n\\n${formatAssistantLabel(labels)}`
      const userTwice = allMessages[index + 1]?.["role"] === "user"
      const lastMessage = index === allMessages.length - 1

      return userTwice || (lastMessage && !ignoreLastInterrupted) ?
        `${accumulator}${userMessage}\\n\\n[Answer Interrupted]\\n\\n` :
        `${accumulator}${userMessage}\\n\\n`
    }

    return accumulator
  }, "")
}

function markdownSession(session, ignoreLastInterrupted = true) {
  const header = session.title ? `## ⌖ ${session.title}\\n\\n---\\n\\n` : ""
  return `${header}${markdownChat(session.messages, ignoreLastInterrupted)}`
}

// Main
function run() {
  const chatFile = `${envVar("alfred_workflow_data")}/chat.json`
  return markdownSession(readSession(chatFile), false)
}"""

HISTORY = """function envVar(varName) {
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

function noArchives() {
  return JSON.stringify({ items: [{
    title: "No Chat Histories Found",
    subtitle: "Archives are created when starting new conversations",
    valid: false
  }]})
}

function run() {
  const archiveDir = `${envVar("alfred_workflow_data")}/archive`
  if (!$.NSFileManager.defaultManager.fileExistsAtPath(archiveDir)) return noArchives()

  const sfItems = dirContents(archiveDir)
    .filter(file => file.endsWith(".json"))
    .toReversed()
    .flatMap(file => {
      const session = readSession(file)
      const firstQuestion = session.messages.find(item => item["role"] === "user")?.["content"]
      const lastQuestion = session.messages.toReversed().find(item => item["role"] === "user")?.["content"]
      const displayTitle = session.title || firstQuestion

      if (!displayTitle) {
        trashChat(file)
        return []
      }

      return {
        type: "file",
        title: displayTitle,
        subtitle: lastQuestion,
        match: `${displayTitle} ${lastQuestion || ""} ${firstQuestion || ""}`,
        arg: file
      }
    })

  if (sfItems.length === 0) return noArchives()

  return JSON.stringify({ items: sfItems })
}"""


def patch_object(obj, uid, script):
    if obj.get("uid") == uid:
        obj["config"]["script"] = script


def main():
    with PLIST_PATH.open("rb") as handle:
        data = plistlib.load(handle)

    for obj in data["objects"]:
        patch_object(obj, "A4782A1E-2A93-401B-9CB7-1D8770AD510E", COPY_LAST)
        patch_object(obj, "361EA732-1619-44FE-991A-3F0120D41C2F", COPY_FULL)
        patch_object(obj, "B2F04B2C-63AD-4A6D-9A81-7F333D0A075A", HISTORY)

        if obj.get("uid") == "4DB440D5-3814-4C79-9724-D19FDDDA4BEC":
            obj["config"]["footertext"] = (
                "↩ Ask · ⌘↩ New chat · /rename Title · "
                "⌥↩ Copy last · ⌃↩ Copy all · ⇧↩ Interrupt"
            )

    readme = data.get("readme", "")
    if "/rename" not in readme:
        readme = readme.replace(
            "* &lt;kbd&gt;↩&lt;/kbd&gt; Ask a new question.",
            "* &lt;kbd&gt;↩&lt;/kbd&gt; Ask a new question.\n"
            "* Type &lt;code&gt;/rename Your title&lt;/code&gt; in the chat dialog to rename the current session.",
        )
        data["readme"] = readme

    data["version"] = "1.1.0"

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    print("Patched rename support in info.plist")


if __name__ == "__main__":
    main()
