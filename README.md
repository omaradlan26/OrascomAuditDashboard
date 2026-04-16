# Orascom Audit Dashboard

This project is now packaged as a Flask application that can run locally or deploy to Vercel using Python serverless functions.

## What changed

- Replaced the local-only Streamlit runtime with a Vercel-compatible Flask app
- Added a `/health` endpoint for deployment checks
- Preserved assignment management, observation intake, filtering, metrics, and charts
- Made production deployments read-only by default so Vercel does not fail on filesystem writes

## Project structure

```text
OrascomAuditDashboard/
|-- api/
|   `-- index.py
|-- assets/
|   `-- orascom-logo.png
|-- data/
|   `-- observations.json
|-- styles/
|   `-- styles.css
|-- templates/
|   `-- dashboard.html
|-- utils/
|   `-- data_handler.py
|-- app.py
|-- requirements.txt
`-- vercel.json
```

## Local run

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
$env:FLASK_APP="app.py"
flask run
```

## Vercel deployment

1. Import the repository into Vercel.
2. Keep the framework preset as `Other`.
3. Deploy with the included `vercel.json`.

### Environment variables

- `OBSERVATIONS_DATA_JSON`
  Use this to ship a fixed JSON snapshot with the deployment. When this variable is set, the app runs in read-only mode.
- `OBSERVATIONS_DATA_FILE`
  Local-development override for the JSON file path.

### Production note

Vercel serverless functions do not provide durable filesystem writes. This app now protects production deployments by switching to read-only mode on Vercel unless you attach a real persistent backend and extend `utils/data_handler.py` to use it.
