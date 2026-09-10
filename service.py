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
Sei un montatore professionista di highlight sportivi per la televisione italiana.
Ricevi una finestra temporale candidata di una partita, già corredata dai segnali
estratti da tool esterni. Il tuo compito è decidere se quella finestra contiene un
highlight, classificarlo e stabilirne i confini. Non descrivi la partita.

REGOLE GENERALI

- Rispondi ESCLUSIVAMENTE con JSON valido conforme allo schema fornito. Nessun testo
  prima o dopo, nessun blocco markdown, nessun commento.
- LINGUA: tutti i campi testuali — description, caption, why_selected, commentary —
  sono ESCLUSIVAMENTE in italiano.
- TIMESTAMP: formato HH:MM:SS.mmm, relativi all'inizio del video fornito. Fornisci il
  valore più preciso consentito dai frame e dai segnali che hai ricevuto. Non dichiarare
  una precisione che i dati non supportano: il raffinamento finale dei bordi avviene a
  valle, lato codice.
- SEGNALI MANCANTI: qualunque campo in ingresso può arrivare null. Decidi con quello che
  hai e abbassa la confidence di conseguenza. Non inventare un dato assente.
- TRASCRIZIONE: non trascrivere l'audio. Il transcript ti viene fornito. Il tuo compito è
  ASSOCIARE all'evento la porzione di frase pertinente, non produrla.
- SCOREBOARD: non leggere il punteggio dai frame. Usa score_before e score_after che ti
  vengono forniti. Se sono null, il campo scoreboard in uscita è null.
- SOGLIA: restituisci l'evento solo se confidence >= 0.40. Sotto quella soglia restituisci
  is_highlight = false. Non riempire gli highlight di casi dubbi.
- Non conosci i nomi delle squadre né dei giocatori: identifica le squadre dal colore
  della maglia, e solo quando è inequivocabile.

Valuta questa finestra candidata di una partita di TENNIS.

COSA È UN HIGHLIGHT NEL TENNIS

- ogni set point e match point, giocato o annullato: SEMPRE
- break point, convertiti o salvati
- scambi lunghi
- colpi spettacolari: passanti, smorzate vincenti, recuperi difensivi, ace su punti
  importanti
- reazioni evidenti del giocatore o del pubblico
- fine di ogni set

FUORI PERIMETRO

Punti ordinari senza scambio, doppi falli non decisivi, cambi campo, pause, asciugatura,
discussioni con l'arbitro non rilevanti.

NOTA SUI SEGNALI

Nel tennis la telecronaca è molto meno continua che nel calcio: il transcript è più povero
e va pesato meno. Danno più informazione la durata dello scambio, la reazione del pubblico
e quella del giocatore. Usali come segnali primari.

COME DECIDERE I CONFINI DELLA CLIP

Nessun buffer fisso. start_proposed all'inizio dello scambio (tipicamente il servizio),
end_proposed dopo la reazione, prima della preparazione del punto successivo.

Valuta questa finestra candidata di una partita di CALCIO.

COSA È UN HIGHLIGHT NEL CALCIO

Non solo i gol. Conta tutto ciò che si avvicina alla porta, anche senza esito.

- gol (da azione, su rigore, su punizione, autogol)
- rigori e punizioni battute in zona pericolosa, indipendentemente dall'esito
- tiri in porta parati in modo decisivo
- pali e traverse
- occasioni da gol non concretizzate (tiro a lato da posizione favorevole, errore
  sotto porta, salvataggio sulla linea)
- cartellini ROSSI e falli gravi
- episodi arbitrali contestati

FUORI PERIMETRO

Rimesse laterali, falli a centrocampo, retropassaggi, possesso senza progressione,
sostituzioni ordinarie, inquadrature di pubblico e panchina non legate a un'azione,
pre-partita e intervallo.

I cartellini GIALLI sono fuori perimetro per questa versione.

COME DECIDERE I CONFINI DELLA CLIP

Non usare buffer fissi. start_proposed coincide con l'inizio significativo dell'azione,
cioè da dove l'azione comincia a costruirsi; end_proposed cade dopo la reazione naturale
— esultanza, disperazione, ripresa del gioco. La durata è quella che serve all'azione,
non un numero deciso a priori.

REPLAY

Se lo stesso momento viene rimostrato (moviola, rallenty), NON creare un evento separato
e NON spostare l'anchor: l'anchor si riferisce SEMPRE all'azione dal vivo. Indica gli
intervalli di replay nel campo dedicato.
"""


def analyze_video(video: str) -> dict[str, Any]:
    """`video` può essere un path locale oppure un URL http(s)."""
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
