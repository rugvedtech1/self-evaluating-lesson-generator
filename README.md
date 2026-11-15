# Self-Evaluating Lesson Content Generator

GenAI Engineer take-home project. Full documentation will be completed in the final step.

## Quick start (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --app-dir backend --reload --reload-dir backend   # http://localhost:8000/health
streamlit run frontend/streamlit_app.py                               # http://localhost:8501
pytest
```
