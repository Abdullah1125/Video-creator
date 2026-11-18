from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import pipeline

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Çocuk Video Stüdyosu")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

LANGUAGES = [
    ("tr", "Türkçe"), ("en", "English"), ("es", "Español"), ("fr", "Français"),
    ("de", "Deutsch"), ("it", "Italiano"), ("pt", "Português"), ("ar", "العربية"),
    ("ru", "Русский"), ("ja", "日本語"), ("ko", "한국어"), ("zh", "中文"),
]

STYLE_PRESETS = [
    "Suluboya çocuk kitabı illüstrasyonu, yumuşak pastel renkler",
    "Basit düz tasarım çizgi film, kalın hatlar ve canlı renkler",
    "Kağıt kesme (papercraft) kolaj, kesik kenarlı kağıt dokusu",
    "El çizimi kroki, pastel kalem dokusu",
    "Keçe/oyun hamuru (claymation) görünümlü yumuşak şekiller",
]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "languages": LANGUAGES, "style_presets": STYLE_PRESETS},
    )


@app.post("/generate")
def generate(
    topic: str = Form(...),
    language: str = Form("tr"),
    design_style: str = Form(...),
    aspect: str = Form("16:9"),
    age_range: str = Form("4-8"),
    duration: int = Form(60),
):
    topic = topic.strip()
    design_style = design_style.strip()
    if not topic:
        raise HTTPException(400, "Konu boş olamaz.")
    if not design_style:
        raise HTTPException(400, "Tasarım tarzı boş olamaz.")
    duration = max(20, min(170, duration))

    job_id = pipeline.new_job_id()
    thread = threading.Thread(
        target=pipeline.run_job,
        args=(job_id, topic, language, design_style, aspect, age_range, duration),
        daemon=True,
    )
    thread.start()
    return JSONResponse({"job_id": job_id})


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    status = pipeline.get_job(job_id)
    if status is None:
        raise HTTPException(404, "İş bulunamadı.")
    return JSONResponse({
        "id": status.id,
        "stage": status.stage,
        "detail": status.detail,
        "progress": status.progress,
        "scenes_done": status.scenes_done,
        "scenes_total": status.scenes_total,
        "error": status.error,
        "ready": status.stage == "done",
    })


@app.get("/jobs/{job_id}/video")
def job_video(job_id: str):
    status = pipeline.get_job(job_id)
    if status is None or status.video_path is None or not status.video_path.exists():
        raise HTTPException(404, "Video henüz hazır değil.")
    return FileResponse(str(status.video_path), media_type="video/mp4", filename=f"{job_id}.mp4")


@app.get("/health")
def health():
    return {"ok": True, "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}
