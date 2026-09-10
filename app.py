import json
import os
import tempfile
import uuid
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, request
from flask_cors import CORS

import db
from service import analyze_video

load_dotenv(override=True)

app = Flask(__name__)
db.init_db()

# In dev il frontend (Vite, http://localhost:5173) gira su un'origine
# diversa dal backend (http://localhost:8080): serve CORS sugli endpoint API.
CORS(app, resources={r"/analyze-video": {"origins": os.getenv("CORS_ORIGINS", "*")},
                      r"/videos": {"origins": os.getenv("CORS_ORIGINS", "*")}})


def _json_response(payload: Any, status: int) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False), status=status, mimetype="application/json")


def _derive_title(highlights: list) -> str:
    """Stessa euristica del frontend (vedi normalizeResult.js): ricava il
    titolo dalle squadre viste negli highlight, per coerenza tra
    l'analisi appena fatta e come poi apparirà nello storico."""
    teams: list[str] = []
    if isinstance(highlights, list):
        for h in highlights:
            team = isinstance(h, dict) and h.get("team")
            if team and team not in teams:
                teams.append(team)
    if len(teams) == 2:
        return f"{teams[0]} vs {teams[1]}"
    if len(teams) == 1:
        return teams[0]
    return "Video analizzato"


def _analyze_and_persist(video: str) -> dict:
    result = analyze_video(video)
    video_id = uuid.uuid4().hex
    title = _derive_title(result)
    db.save_video(video_id, title, result)
    return {"result": result, "video_id": video_id, "title": title}


@app.post("/analyze-video")
def analyze_video_endpoint() -> Response:
    video_file = request.files.get("video")

    if video_file and video_file.filename:
        suffix = os.path.splitext(video_file.filename)[1] or ".mp4"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        video_file.save(tmp_path)
        try:
            payload = _analyze_and_persist(tmp_path)
            return _json_response(payload, 200)
        except Exception as exc:
            return _json_response({"error": str(exc)}, 500)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    data = request.get_json(silent=True) or {}
    video_url = (data.get("video_url") or "").strip()

    if not video_url:
        return _json_response({"error": "video_url or a 'video' file upload is required"}, 400)

    try:
        payload = _analyze_and_persist(video_url)
        return _json_response(payload, 200)
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)


@app.get("/videos")
def list_videos_endpoint() -> Response:
    return _json_response(db.list_videos(), 200)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
