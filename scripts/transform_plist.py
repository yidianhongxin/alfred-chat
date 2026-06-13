#!/usr/bin/env python3
"""Transform openai-workflow info.plist into Alfred Chat workflow."""

import json
import plistlib
import re
from copy import deepcopy
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / "Workflow"
PLIST_PATH = WORKFLOW_DIR / "info.plist"

DALLE_MARKERS = (
    "dalle",
    "DALL·E",
    "DALL-E",
    "continue_images",
    "dalle_images_folder",
)

NEW_USER_CONFIG = [
    {
        "config": {
            "default": "chat",
            "placeholder": "",
            "required": False,
            "trim": True,
        },
        "description": "",
        "label": "Chat Keyword",
        "type": "textfield",
        "variable": "chat_keyword",
    },
    {
        "config": {
            "default": "minimax",
            "pairs": [
                ["DeepSeek", "deepseek"],
                ["MiniMax", "minimax"],
            ],
        },
        "description": "Choose which API provider to use for chat.",
        "label": "Provider",
        "type": "popupbutton",
        "variable": "chat_provider",
    },
    {
        "config": {
            "default": "",
            "placeholder": "",
            "required": False,
            "trim": True,
        },
        "description": "Get it at https://platform.deepseek.com/api_keys",
        "label": "DeepSeek API Key",
        "type": "textfield",
        "variable": "deepseek_api_key",
    },
    {
        "config": {
            "default": "deepseek-v4-flash",
            "pairs": [
                ["DeepSeek V4 Flash", "deepseek-v4-flash"],
                ["DeepSeek V4 Pro", "deepseek-v4-pro"],
                ["DeepSeek Chat (legacy)", "deepseek-chat"],
                ["DeepSeek Reasoner (legacy)", "deepseek-reasoner"],
            ],
        },
        "description": "",
        "label": "DeepSeek Model",
        "type": "popupbutton",
        "variable": "deepseek_model",
    },
    {
        "config": {
            "default": "",
            "placeholder": "",
            "required": False,
            "trim": True,
        },
        "description": "Get it at https://platform.minimax.io/user-center/basic-information/interface-key",
        "label": "MiniMax API Key",
        "type": "textfield",
        "variable": "minimax_api_key",
    },
    {
        "config": {
            "default": "china",
            "pairs": [
                ["International (api.minimax.io)", "international"],
                ["China (api.minimaxi.com)", "china"],
            ],
        },
        "description": "Select the MiniMax API region.",
        "label": "MiniMax Region",
        "type": "popupbutton",
        "variable": "minimax_region",
    },
    {
        "config": {
            "default": "MiniMax-M2.7-highspeed",
            "pairs": [
                ["MiniMax M2.7 Highspeed", "MiniMax-M2.7-highspeed"],
                ["MiniMax M2.7", "MiniMax-M2.7"],
                ["MiniMax M3", "MiniMax-M3"],
                ["MiniMax M2.5 Highspeed", "MiniMax-M2.5-highspeed"],
                ["MiniMax M2.5", "MiniMax-M2.5"],
            ],
        },
        "description": "",
        "label": "MiniMax Model",
        "type": "popupbutton",
        "variable": "minimax_model",
    },
    {
        "config": {
            "default": True,
            "required": False,
            "text": "Save current chat when starting a new one",
        },
        "description": "",
        "label": "Keep History",
        "type": "checkbox",
        "variable": "chat_history_save",
    },
    {
        "config": {
            "defaultvalue": 24,
            "markercount": 25,
            "maxvalue": 50,
            "minvalue": 2,
            "onlystoponmarkers": True,
            "showmarkers": True,
        },
        "description": "How many older questions and answers to send.",
        "label": "Context",
        "type": "slider",
        "variable": "max_context",
    },
    {
        "config": {
            "defaultvalue": 30,
            "markercount": 6,
            "maxvalue": 60,
            "minvalue": 5,
            "onlystoponmarkers": True,
            "showmarkers": True,
        },
        "description": "How many seconds to wait before giving up connection.",
        "label": "Timeout",
        "type": "slider",
        "variable": "timeout_seconds",
    },
    {
        "config": {
            "default": "",
            "required": False,
            "trim": True,
            "verticalsize": 3,
        },
        "description": "Initial message to guide the assistant on the answers you expect.",
        "label": "System Prompt",
        "type": "textarea",
        "variable": "system_prompt",
    },
]

NEW_README = """## Setup

1. Open the Workflow Configuration in Alfred Preferences.
2. Choose **DeepSeek** or **MiniMax** as your provider.
3. Add the corresponding API key:
   - DeepSeek: https://platform.deepseek.com/api_keys
   - MiniMax: https://platform.minimax.io/user-center/basic-information/interface-key
4. Adjust model, region, and system prompt as needed.

## Usage

### Chat

Query via the `chat` keyword, the [Universal Action](https://www.alfredapp.com/help/features/universal-actions/), or the [Fallback Search](https://www.alfredapp.com/help/features/default-results/fallback-searches/).

* <kbd>↩</kbd> Ask a new question.
* <kbd>⌘</kbd><kbd>↩</kbd> Clear and start new chat.
* <kbd>⌥</kbd><kbd>↩</kbd> Copy last answer.
* <kbd>⌃</kbd><kbd>↩</kbd> Copy full chat.
* <kbd>⇧</kbd><kbd>↩</kbd> Stop generating answer.

#### Chat History

View Chat History with ⌥↩ on the `chat` keyword. Each result shows the first question as the title and the last as the subtitle.

<kbd>↩</kbd> to archive the current chat and load the selected one. Older chats can be trashed with the `Delete` [Universal Action](https://www.alfredapp.com/help/features/universal-actions/). Select multiple chats with the [File Buffer](https://www.alfredapp.com/help/features/file-search/#file-buffer).

## Advanced

Override API endpoints via Workflow Environment Variables:

* `deepseek_api_endpoint` — default `https://api.deepseek.com/chat/completions`
* `minimax_api_endpoint` — default depends on MiniMax Region setting"""


def object_blob(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False).lower()


def is_dalle_object(obj: dict) -> bool:
    blob = object_blob(obj)
    return any(marker.lower() in blob for marker in DALLE_MARKERS)


def replace_strings(value):
    if isinstance(value, str):
        replacements = [
            ("com.alfredapp.vitor.openai", "com.drlerr.alfred-chat"),
            ("ChatGPT / DALL-E", "Alfred Chat"),
            ("OpenAI integrations", "DeepSeek & MiniMax chat"),
            ("Ask ChatGPT '{query}'", "Ask AI '{query}'"),
            ("Ask ChatGPT", "Ask AI"),
            ("Querying ChatGPT API…", "Querying API…"),
            ("ChatGPT Chat History", "Chat History"),
            ("{var:chatgpt_keyword}", "{var:chat_keyword}"),
            ("{var:chatgpt_history_save}", "{var:chat_history_save}"),
            ("chatgpt_history_save", "chat_history_save"),
            ("chatgpt_keyword", "chat_keyword"),
            ("https://github.com/alfredapp/openai-workflow/", ""),
            ("Vítor Galvão", "DRLer"),
        ]
        result = value
        for old, new in replacements:
            result = result.replace(old, new)
        if result == "chatgpt":
            return "chat"
        return result
    if isinstance(value, list):
        return [replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {replace_strings(k): replace_strings(v) for k, v in value.items()}
    return value


def prune_connections(connections: dict, removed_uids: set[str]) -> dict:
    pruned = {}
    for source_uid, targets in connections.items():
        if source_uid in removed_uids:
            continue
        kept_targets = [
            target
            for target in targets
            if target.get("destinationuid") not in removed_uids
        ]
        if kept_targets:
            pruned[source_uid] = kept_targets
    return pruned


def main() -> None:
    with PLIST_PATH.open("rb") as handle:
        data = plistlib.load(handle)

    removed_uids = {
        obj["uid"]
        for obj in data["objects"]
        if is_dalle_object(obj)
    }

    data["objects"] = [
        obj for obj in data["objects"] if obj["uid"] not in removed_uids
    ]
    data["connections"] = prune_connections(data["connections"], removed_uids)
    data["uidata"] = {
        uid: position
        for uid, position in data["uidata"].items()
        if uid not in removed_uids
    }

    data = replace_strings(data)

    data["bundleid"] = "com.drlerr.alfred-chat"
    data["name"] = "Alfred Chat"
    data["description"] = "DeepSeek & MiniMax chat"
    data["createdby"] = "DRLer"
    data["version"] = "1.0.0"
    data["readme"] = NEW_README
    data["webaddress"] = ""
    data["userconfigurationconfig"] = deepcopy(NEW_USER_CONFIG)
    data["variables"] = {
        "deepseek_api_endpoint": "",
        "minimax_api_endpoint": "",
    }

    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)

    print(f"Removed {len(removed_uids)} DALL·E-related objects")
    print(f"Remaining objects: {len(data['objects'])}")


if __name__ == "__main__":
    main()
