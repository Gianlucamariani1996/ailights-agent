import json
import os
import shutil
import tempfile
import uuid
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, request, send_from_directory
from flask_cors import CORS

import db
import reel
from service import analyze_video

load_dotenv(override=True)

app = Flask(__name__)
db.init_db()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In dev il frontend (Vite, http://localhost:5173) gira su un'origine
# diversa dal backend (http://localhost:8080): serve CORS sugli endpoint API.
CORS(app, resources={r"/analyze-video": {"origins": os.getenv("CORS_ORIGINS", "*")},
                      r"/videos": {"origins": os.getenv("CORS_ORIGINS", "*")},
                      r"/videos/*": {"origins": os.getenv("CORS_ORIGINS", "*")}})


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


def _persist(result: list, video_url: str | None = None, video_id: str | None = None) -> dict:
    video_id = video_id or uuid.uuid4().hex
    title = _derive_title(result)
    db.save_video(video_id, title, result, video_url)
    return {"result": result, "video_id": video_id, "title": title, "video_url": video_url}


@app.post("/analyze-video")
def analyze_video_endpoint() -> Response:
    video_file = request.files.get("video")

    if video_file and video_file.filename:
        suffix = os.path.splitext(video_file.filename)[1] or ".mp4"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        video_file.save(tmp_path)
        try:
            result = analyze_video(tmp_path)
            # Solo dopo un'analisi riuscita copiamo il video in una cartella
            # persistente (servita da /uploads/<file>), così lo storico può
            # ripuntarci anche dopo un refresh: il file temporaneo va comunque
            # rimosso a prescindere (vedi finally).
            video_id = uuid.uuid4().hex
            stored_name = f"{video_id}{suffix}"
            shutil.copyfile(tmp_path, os.path.join(UPLOAD_DIR, stored_name))
            payload = _persist(result, video_url=f"/uploads/{stored_name}", video_id=video_id)
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
        result = analyze_video(video_url)
        # Qui il video vive già altrove: nessun file da copiare, basta
        # riusare lo stesso video_url anche come riferimento persistito.
        payload = _persist(result, video_url=video_url)
        return _json_response(payload, 200)
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)


@app.get("/videos")
def list_videos_endpoint() -> Response:
    return _json_response(db.list_videos(), 200)


@app.get("/uploads/<path:filename>")
def uploaded_file(filename: str) -> Response:
    return send_from_directory(UPLOAD_DIR, filename)


def _resolve_source(video_url: str | None) -> str | None:
    """Un video_url che punta a /uploads/... va tradotto nel path locale
    reale: ffmpeg ha bisogno del file, non della route Flask che lo serve.
    Un URL esterno assoluto (analisi partita da video_url remoto) invece
    va bene così com'è: ffmpeg legge anche sorgenti HTTP."""
    if not video_url:
        return None
    if video_url.startswith("/uploads/"):
        return os.path.join(UPLOAD_DIR, os.path.basename(video_url))
    return video_url


@app.post("/videos/<video_id>/reel")
def generate_reel_endpoint(video_id: str) -> Response:
    record = db.get_video(video_id)
    if record is None:
        return _json_response({"error": "Video non trovato."}, 404)

    source = _resolve_source(record["video_url"])
    if not source:
        return _json_response({"error": "Nessun video sorgente disponibile per questo id."}, 400)

    try:
        output_path = reel.build_reel(video_id, source, record["result"])
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)

    return _json_response({"reel_url": f"/reels/{os.path.basename(output_path)}"}, 200)


@app.get("/reels/<path:filename>")
def reel_file(filename: str) -> Response:
    return send_from_directory(reel.REELS_DIR, filename)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
