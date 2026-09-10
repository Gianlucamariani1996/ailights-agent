# Ailights Agent

Agente per l'analisi di video tramite AI. Espone un'API HTTP (Flask) con due endpoint: `/analyze-video` e `/videos`.

## Cosa fa

- Riceve l'URL (o il file) di un video da analizzare.
- Delega l'analisi a un servizio (`service.py`) che scarica il video, lo carica su Gemini e ne estrae gli highlight in formato JSON.
- Ogni analisi viene salvata in un DB SQLite locale (`videos.db`, vedi `db.py`): id, titolo (derivato dalle squadre viste negli highlight) e il JSON del risultato. `GET /videos` espone lo storico per il frontend.

## API

- `POST /analyze-video`: richiede l'analisi di un video. Accetta uno dei due:

  **Body JSON (URL remoto):**
  ```json
  {
    "video_url": "https://example.com/video.mp4"
  }
  ```

  **`multipart/form-data` (file locale):** campo `video` con il file da analizzare.
  ```bash
  curl -F "video=@/path/locale/video.mp4" http://localhost:8080/analyze-video
  ```

  **Risposta (200):**
  ```json
  {
    "result": [ { "type": "gol", "start": "45:33", "end": "46:10", "team": "...", "description": "...", "relevance": 95 }, ... ],
    "video_id": "080c2f5838fd4518a676298366866766",
    "title": "Squadra A vs Squadra B"
  }
  ```

  **Risposta (400):** né `video_url` né un file `video` sono stati forniti.

  **Risposta (500):** errore durante l'analisi (es. chiave Gemini mancante o errore dell'API).

- `GET /videos`: storico delle analisi salvate, più recenti prime.

  **Risposta (200):**
  ```json
  [
    { "id": "...", "title": "...", "created_at": "2026-09-10T16:24:56+00:00", "result": [ ... ] }
  ]
  ```

## Variabili d'ambiente

- `HOST`: host del server (default `0.0.0.0`).
- `PORT`: porta del server (default `8080`).
- `FLASK_DEBUG`: abilita il debug mode (0 o 1).
- `GEMINI_API_KEY` (o `GOOGLE_API_KEY`): chiave API di Gemini, richiesta per l'analisi video.
- `GEMINI_MODEL`: modello Gemini da usare (default `gemini-3.8-flash`).
- `MOCK_ANALYSIS`: se `1`, `/analyze-video` non chiama Gemini e restituisce un risultato fisso (utile per sviluppare il frontend senza consumare quota API).

## Installazione e avvio

1. [uv](https://docs.astral.sh/uv/) installato (gestisce Python, ambiente virtuale e dipendenze).
2. Creazione dell'ambiente virtuale: `uv venv`.
3. Installazione delle dipendenze: `uv pip install -r requirements.txt`.
4. Avvio del server: `uv run app.py`.

