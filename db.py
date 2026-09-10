"""Storage SQLite per i video analizzati (usato dallo storico).

Salva id, titolo e il JSON grezzo restituito dall'analisi. Nessun file
video viene persistito: solo i metadati e il risultato dell'analisi.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.path.join(os.path.dirname(__file__), "videos.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                result TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_video(video_id: str, title: str, result: Any) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO videos (id, title, created_at, result) VALUES (?, ?, ?, ?)",
            (video_id, title, datetime.now(timezone.utc).isoformat(), json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def list_videos() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, result FROM videos ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "result": json.loads(row["result"]),
        }
        for row in rows
    ]
