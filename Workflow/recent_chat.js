#!/usr/bin/osascript -l JavaScript

function envVar(varName) {
  return $.NSProcessInfo.processInfo.environment.objectForKey(varName).js
}

function workflowDataDir() {
  return envVar("alfred_workflow_data") ||
    `${envVar("HOME")}/Library/Application Support/Alfred/Workflow Data/com.drlerr.alfred-chat`
}

function dirContents(path) {
  return $.NSFileManager.defaultManager
    .contentsOfDirectoryAtURLIncludingPropertiesForKeysOptionsError(
      $.NSURL.fileURLWithPath(path),
      undefined,
      $.NSDirectoryEnumerationSkipsHiddenFiles,
      undefined
    )
    .js.map(item => item.path.js)
    .sort()
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

function makeDir(path) {
  $.NSFileManager.defaultManager.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(
    path, true, undefined, undefined)
}

function writeFile(path, text) {
  $(text).writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, undefined)
}

function mv(fromPath, toPath) {
  $.NSFileManager.defaultManager.moveItemAtPathToPathError(fromPath, toPath, undefined)
}

function padDate(number) {
  return number.toString().padStart(2, "0")
}

function findRecentChatPath(currentChat, archiveDir) {
  const fileManager = $.NSFileManager.defaultManager

  if (fileManager.fileExistsAtPath(currentChat)) {
    try {
      if (readSession(currentChat).messages.length > 0) return currentChat
    } catch {}
  }

  if (fileManager.fileExistsAtPath(archiveDir)) {
    const archives = dirContents(archiveDir)
      .filter(file => file.endsWith(".json"))
      .sort()
      .reverse()

    if (archives.length > 0) return archives[0]
  }

  return currentChat
}

function loadRecentChat() {
  const dataDir = workflowDataDir()
  const currentChat = `${dataDir}/chat.json`
  const archiveDir = `${dataDir}/archive`
  const replacementChat = findRecentChatPath(currentChat, archiveDir)

  if (replacementChat && replacementChat === currentChat) return

  const uid = $.NSProcessInfo.processInfo.globallyUniqueString.js.split("-")[0]
  const now = new Date()
  const archivedChat = `${archiveDir}/${now.getFullYear()}.${padDate(now.getMonth() + 1)}.${padDate(now.getDate())}.${padDate(now.getHours())}.${padDate(now.getMinutes())}.${padDate(now.getSeconds())}-${uid}.json`

  makeDir(archiveDir)
  mv(currentChat, archivedChat)

  if (replacementChat && replacementChat !== archivedChat)
    mv(replacementChat, currentChat)
  else
    writeFile(currentChat, "[]")
}

function run() {
  loadRecentChat()
}
