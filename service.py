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

Sono highlight: gol, rigori e punizioni in zona pericolosa, pali, parate
decisive, occasioni da gol non concretizzate.
NON sono highlight: rimesse, falli a centrocampo, sostituzioni ordinarie.
Se non trovi nessun highlight, restituisci [].

"start" ed "end" devono delimitare SOLO l'azione dal vivo: l'evento deve
comparire una volta sola nella clip, non due. Se subito dopo l'azione va in
onda un replay/rallenty/moviola dello stesso episodio, NON allungare "end"
per includerlo: la clip finisce con la reazione naturale dal vivo
(esultanza, ripresa del gioco), prima che parta il replay. Un evento tipico
dura pochi secondi: se stai per superare i 30-40 secondi, probabilmente hai
incluso un replay per errore.

Il campo "type" deve usare ESATTAMENTE uno di questi valori, senza varianti
né sinonimi: "gol", "rigore", "palo", "parata", "occasione da gol".

Schema di ogni evento:
{"type": "gol|rigore|palo|parata|occasione da gol", "start": "mm:ss",
"end": "mm:ss", "team": "...", "description": "...", "relevance": 0-100}
"""


_MOCK_HIGHLIGHTS: list[dict[str, Any]] = [
  {
    "type": "parata",
    "start": "26:33",
    "end": "26:47",
    "team": "Roma",
    "description": "Džeko semina il panico nell'area della Lazio e calcia a botta sicura verso l'angolino, ma Strakosha si distende e compie una grande parata.",
    "relevance": 80
  },
  {
    "type": "parata",
    "start": "28:04",
    "end": "28:17",
    "team": "Roma",
    "description": "Pastore si inserisce in area e conclude con un diagonale mancino ravvicinato, Strakosha respinge d'istinto con i piedi.",
    "relevance": 80
  },
  {
    "type": "parata",
    "start": "28:50",
    "end": "29:05",
    "team": "Lazio",
    "description": "Immobile controlla e si gira in un fazzoletto calciando con potenza verso la porta, Olsen vola a deviare sopra la traversa.",
    "relevance": 85
  },
  {
    "type": "occasione",
    "start": "29:45",
    "end": "30:15",
    "team": "Roma",
    "description": "Ripartenza fulminea della Roma: Džeko allarga per Florenzi, fermato solo da un provvidenziale recupero in scivolata di Luiz Felipe.",
    "relevance": 75
  },
  {
    "type": "occasione",
    "start": "31:07",
    "end": "31:30",
    "team": "Roma",
    "description": "Calcio d'angolo battuto sul primo palo, spizzata di testa di Nzonzi che attraversa lo specchio della porta ma De Rossi non ci arriva per un soffio.",
    "relevance": 80
  },
  {
    "type": "gol",
    "start": "48:18",
    "end": "49:15",
    "team": "Roma",
    "description": "Pasticcio difensivo della retroguardia laziale a seguito di un duello aereo di Džeko: sul pallone vagante si avventa Lorenzo Pellegrini che sblocca il derby con un colpo di tacco magistrale.",
    "relevance": 98
  }
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
