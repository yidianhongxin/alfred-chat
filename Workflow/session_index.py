#!/usr/bin/env python3
"""SQLite FTS5 index for Alfred Chat session history."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def data_dir() -> Path:
    path = Path(os.environ.get("alfred_workflow_data") or os.environ.get("ALFRED_WORKFLOW_DATA") or "/tmp/alfred-chat")
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "state.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            source TEXT PRIMARY KEY,
            title TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content,
            role,
            session_source,
            title,
            tokenize='unicode61'
        );
        """
    )
    conn.commit()


def parse_session_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"title": None, "messages": []}
    if isinstance(data, list):
        return {"title": None, "messages": data}
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return {"title": data.get("title"), "messages": data["messages"]}
    return {"title": None, "messages": []}


def session_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return datetime.now().isoformat(timespec="seconds")


def index_session(conn: sqlite3.Connection, path: Path, source: str) -> int:
    session = parse_session_file(path)
    title = session.get("title") or path.stem
    updated = session_mtime(path)

    conn.execute("DELETE FROM messages_fts WHERE session_source = ?", (source,))
    count = 0
    for message in session.get("messages", []):
        role = message.get("role", "")
        content = (message.get("content") or "").strip()
        if not content:
            continue
        conn.execute(
            "INSERT INTO messages_fts(content, role, session_source, title) VALUES (?, ?, ?, ?)",
            (content, role, source, title),
        )
        count += 1

    conn.execute(
        """
        INSERT INTO sessions(source, title, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at
        """,
        (source, title, updated),
    )
    conn.commit()
    return count


def rebuild_index() -> int:
    root = data_dir()
    conn = connect()
    init_db(conn)
    conn.execute("DELETE FROM messages_fts")
    conn.execute("DELETE FROM sessions")

    total = 0
    chat_file = root / "chat.json"
    if chat_file.exists():
        total += index_session(conn, chat_file, "current")

    archive = root / "archive"
    if archive.exists():
        for path in sorted(archive.glob("*.json")):
            total += index_session(conn, path, f"archive/{path.name}")

    conn.close()
    return total


def ensure_indexed() -> None:
    root = data_dir()
    conn = connect()
    init_db(conn)
    chat_file = root / "chat.json"
    if chat_file.exists():
        source = "current"
        mtime = session_mtime(chat_file)
        row = conn.execute("SELECT updated_at FROM sessions WHERE source = ?", (source,)).fetchone()
        if not row or row["updated_at"] != mtime:
            index_session(conn, chat_file, source)
    conn.close()


def search_sessions(term: str, limit: int = 8) -> List[Dict[str, str]]:
    ensure_indexed()
    query = term.strip()
    if not query:
        return []

    import re

    safe = re.sub(r"[^\w\u4e00-\u9fa5\s]", " ", query)
    tokens = [token for token in safe.split() if token]
    queries: List[str] = [f'"{query}"']
    if tokens:
        queries.append(" OR ".join(f'"{token}"' for token in tokens))
        queries.append(" ".join(tokens))
        queries.append(" OR ".join(f"{token}*" for token in tokens if len(token) >= 2))

    conn = connect()
    init_db(conn)
    rows = []
    for fts_query in queries:
        try:
            rows = conn.execute(
                """
                SELECT session_source, title, role, snippet(messages_fts, 0, '[', ']', '…', 24) AS snippet
                FROM messages_fts
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if rows:
            break

    if not rows:
        rows = conn.execute(
            """
            SELECT session_source, title, role, substr(content, 1, 120) AS snippet
            FROM messages_fts
            WHERE content LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()

    conn.close()

    results: List[Dict[str, str]] = []
    for row in rows:
        results.append(
            {
                "session": row["session_source"],
                "title": row["title"] or "",
                "role": row["role"] or "",
                "snippet": row["snippet"] or "",
            }
        )
    return results


def format_search_results(term: str, results: List[Dict[str, str]]) -> str:
    if not results:
        return f"未在对话历史中找到与「{term}」相关的内容。"

    lines = [f"对话搜索「{term}」共 {len(results)} 条：", ""]
    for item in results:
        lines.append(f"- [{item['session']}] {item['title']} ({item['role']})")
        lines.append(f"  {item['snippet']}")
    return "\n".join(lines)


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--rebuild":
        count = rebuild_index()
        print(json.dumps({"indexed_messages": count}, ensure_ascii=False))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "--search":
        term = sys.argv[2]
        results = search_sessions(term)
        print(format_search_results(term, results))
        return

    rebuild_index()
    print(json.dumps({"ok": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
