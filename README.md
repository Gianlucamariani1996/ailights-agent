# Ailights Agent

Agente per l'analisi di video tramite AI. Espone un'API HTTP (Flask) con un unico endpoint `/analyze-video`.

## Cosa fa

- Riceve l'URL di un video da analizzare.
- Delega l'analisi a un servizio (`service.py`) che scarica il video, lo carica su Gemini e ne estrae riassunto, highlights e tag in formato JSON.

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
    "result": { ... }
  }
  ```

  **Risposta (400):** né `video_url` né un file `video` sono stati forniti.

  **Risposta (500):** errore durante l'analisi (es. chiave Gemini mancante o errore dell'API).

## Variabili d'ambiente

- `HOST`: host del server (default `0.0.0.0`).
- `PORT`: porta del server (default `8080`).
- `FLASK_DEBUG`: abilita il debug mode (0 o 1).
- `GEMINI_API_KEY` (o `GOOGLE_API_KEY`): chiave API di Gemini, richiesta per l'analisi video.
- `GEMINI_MODEL`: modello Gemini da usare (default `gemini-3.8-flash`).

## Installazione e avvio

1. [uv](https://docs.astral.sh/uv/) installato (gestisce Python, ambiente virtuale e dipendenze).
2. Creazione dell'ambiente virtuale: `uv venv`.
3. Installazione delle dipendenze: `uv pip install -r requirements.txt`.
4. Avvio del server: `uv run app.py`.

