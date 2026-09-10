"""Genera l'highlight reel: ritaglia ogni highlight dal video sorgente e li
concatena in un unico mp4, usando ffmpeg (deve essere nel PATH).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

REELS_DIR = os.path.join(os.path.dirname(__file__), "reels")
os.makedirs(REELS_DIR, exist_ok=True)

_TIME_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def _parse_time(value: str) -> float:
    """'mm:ss' o 'hh:mm:ss' -> secondi."""
    match = _TIME_RE.match((value or "").strip())
    if not match:
        return 0.0
    h, m, s = match.groups()
    return int(h or 0) * 3600 + int(m) * 60 + float(s)


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def build_reel(video_id: str, source: str, highlights: list[dict[str, Any]]) -> str:
    """Genera (o riusa, se già presente) il reel per `video_id`.

    `source` è il path locale o l'URL da cui ffmpeg legge il video
    originale. Restituisce il path assoluto del file mp4 risultante.
    """
    if not has_ffmpeg():
        raise RuntimeError("ffmpeg non è installato o non è nel PATH del server.")
    if not highlights:
        raise RuntimeError("Nessun highlight da assemblare per questo video.")

    output_path = os.path.join(REELS_DIR, f"{video_id}.mp4")
    if os.path.isfile(output_path):
        return output_path

    with tempfile.TemporaryDirectory() as tmp_dir:
        clip_paths = []
        for i, h in enumerate(highlights):
            start = _parse_time(h.get("start"))
            end = _parse_time(h.get("end"))
            duration = max(0.1, end - start)
            clip_path = os.path.join(tmp_dir, f"clip_{i:03d}.mp4")
            _run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", source,
                    "-t", str(duration),
                    "-c:v", "libx264", "-preset", "veryfast",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    clip_path,
                ]
            )
            clip_paths.append(clip_path)

        list_path = os.path.join(tmp_dir, "list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                output_path,
            ]
        )

    return output_path


def _run_ffmpeg(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg ha fallito ({' '.join(cmd[:4])}...): {proc.stderr[-2000:]}")
