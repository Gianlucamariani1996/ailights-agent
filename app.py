import json
import os
import tempfile

from dotenv import load_dotenv
from flask import Flask, Response, request
from flask_cors import CORS

from service import analyze_video

load_dotenv(override=True)

app = Flask(__name__)

# In dev il frontend (Vite, http://localhost:5173) gira su un'origine
# diversa dal backend (http://localhost:8080): serve CORS sull'endpoint API.
CORS(app, resources={r"/analyze-video": {"origins": os.getenv("CORS_ORIGINS", "*")}})


def _json_response(payload: dict, status: int) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False), status=status, mimetype="application/json")


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
            return _json_response({"result": result}, 200)
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
        return _json_response({"result": result}, 200)
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
