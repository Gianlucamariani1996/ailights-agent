"""Video analysis service.

Resolves the analysis of a video given a local path or an http(s) URL.
The actual analysis is delegated to Gemini.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any
from urllib.parse import urlparse

import requests
from google import genai
from google.genai import types

SYSTEM_PROMPT = """\
Sei un montatore di highlight sportivi.
Analizza questo video di calcio e restituisci ESCLUSIVAMENTE un array JSON.

Sono highlight: gol, rigori, punizioni pericolose, pali, parate decisive,
occasioni da gol non concretizzate.
NON sono highlight: rimesse, falli a centrocampo, sostituzioni ordinarie.
Se non trovi nessun highlight, restituisci [].

Schema di ogni evento:
{"type": "...", "start": "mm:ss", "end": "mm:ss", "team": "...",
"description": "...", "relevance": 0-100}
"""


_MOCK_HIGHLIGHTS: list[dict[str, Any]] = [
    {"type": "occasione da gol", "start": "08:12", "end": "08:24", "team": "Juventus", "description": "Contropiede rapido della Juventus: Vlahovic allarga per Cuadrado che calcia di potenza incrociando a fil di palo.", "relevance": 72},
    {"type": "parata", "start": "11:52", "end": "12:06", "team": "Juventus", "description": "Azione corale della Juventus, velo di Vlahovic e conclusione mancina di prima intenzione di Milik, respinta da Tatarusanu.", "relevance": 75},
    {"type": "occasione da gol", "start": "12:54", "end": "13:06", "team": "Juventus", "description": "Danilo approfitta dello spazio al limite dell'area e scaglia un violento diagonale destro che finisce di poco a lato.", "relevance": 70},
    {"type": "palo", "start": "20:03", "end": "20:25", "team": "Milan", "description": "Sugli sviluppi di un calcio d'angolo di Tonali, colpo di tacco di Rafael Leão che si stampa direttamente sul palo a Szczesny battuto.", "relevance": 88},
    {"type": "palo", "start": "33:55", "end": "34:15", "team": "Milan", "description": "Rafael Leão si accentra dalla sinistra e scocca una splendida conclusione da fuori area che colpisce in pieno la base del palo.", "relevance": 89},
    {"type": "gol", "start": "45:33", "end": "46:10", "team": "Milan", "description": "Calcio d'angolo teso battuto da Theo Hernandez, conclusione al volo di Giroud controllata e girata in rete da distanza ravvicinata da Fikayo Tomori per l'1-0.", "relevance": 95},
]


def analyze_video(video: str) -> Any:
    """`video` può essere un path locale oppure un URL http(s).

    Se MOCK_ANALYSIS=1 è impostata, non chiama Gemini: restituisce un
    risultato fisso, utile per sviluppare il frontend senza consumare
    quota API o attendere l'elaborazione reale del video.
    """
    if os.environ.get("MOCK_ANALYSIS") == "1":
        return _MOCK_HIGHLIGHTS
    return _call_gemini(video)


def _call_gemini(video: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY non impostata.")

    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=api_key)

    # Se è un URL, scaricalo in un file temporaneo; altrimenti usa il path locale.
    downloaded_path = None
    if urlparse(video).scheme in ("http", "https"):
        suffix = os.path.splitext(urlparse(video).path)[1] or ".mp4"
        fd, downloaded_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f, requests.get(video, stream=True, timeout=120) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        local_path = downloaded_path
    else:
        if not os.path.isfile(video):
            raise RuntimeError(f"File video non trovato: {video}")
        local_path = video

    uploaded = None
    try:
        # Upload sulla Files API e attesa dello stato ACTIVE.
        uploaded = client.files.upload(file=local_path)
        if not uploaded.name:
            raise RuntimeError("Gemini non ha restituito un nome per il file caricato.")
        file_name = uploaded.name
        waited = 0
        while not uploaded.state or uploaded.state.name not in ("ACTIVE", "FAILED"):
            if waited >= 600:
                raise RuntimeError("Timeout: il video non è diventato ACTIVE entro 10 minuti.")
            time.sleep(3)
            waited += 3
            uploaded = client.files.get(name=file_name)
        if uploaded.state.name == "FAILED":
            raise RuntimeError(f"Gemini non è riuscito a processare il video: {uploaded!r}")

        # Generazione con output forzato a JSON.
        response = client.models.generate_content(
            model=model,
            contents=[uploaded],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )

        # Parsing (tollerante a eventuali code fence).
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text or "", flags=re.MULTILINE).strip()
        return json.loads(text)

    finally:
        if uploaded is not None and uploaded.name:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
        if downloaded_path:
            try:
                os.remove(downloaded_path)
            except OSError:
                pass
