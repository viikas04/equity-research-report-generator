"""
main.py — FastAPI app. One real endpoint: upload a context document + company
name, get back a downloadable PDF research report.

Security measures (deliberately kept simple, appropriate to this app's scope
- see README "Security" section for what was and wasn't added, and why):
  - File size capped to prevent resource-exhaustion from huge uploads
  - File extension allow-list (not just trusted from content-type header)
  - Company name / filenames sanitized before touching the filesystem
  - Uploaded source file always deleted after use, even on failure
  - Generated PDF deleted after being sent to the client (not left on disk)
"""

import re
import shutil
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # picks up GEMINI_API_KEY from a local .env file if present

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from extract import process_document
from render import render_report_pdf

app = FastAPI(title="Bull AI — Research Report Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # OK for local/demo use; restrict to a real origin before any public deployment
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path(tempfile.gettempdir()) / "bull_ai_reports"
OUTPUT_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".txt", ".md"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB — generous for a financial doc, small enough to block abuse


def _safe_slug(name: str, fallback: str = "company") -> str:
    """Strip anything that isn't alphanumeric/space/dash before it touches a
    filename, so a company name can never be used to write outside the
    intended output directory or inject odd characters into a path."""
    cleaned = re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or fallback


@app.post("/api/generate-report")
async def generate_report(
    background_tasks: BackgroundTasks,
    company_name: str = Form(...),
    file: UploadFile = File(...),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    # Enforce the size cap by reading in chunks rather than trusting a
    # Content-Length header, which a client can lie about.
    job_id = uuid.uuid4().hex[:10]
    upload_path = OUTPUT_DIR / f"{job_id}_source{ext}"
    total = 0
    with upload_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                out.close()
                upload_path.unlink(missing_ok=True)
                raise HTTPException(413, f"File too large. Max size is {MAX_UPLOAD_BYTES // (1024*1024)}MB.")
            out.write(chunk)

    safe_company = _safe_slug(company_name)

    try:
        extracted = process_document(str(upload_path))
        extracted.setdefault("meta", {})["company_name"] = extracted["meta"].get("company_name") or company_name

        output_path = OUTPUT_DIR / f"{job_id}_report.pdf"
        render_report_pdf(extracted, str(output_path))
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}") from e
    finally:
        upload_path.unlink(missing_ok=True)

    # Clean up the generated PDF after it's been streamed to the client —
    # nothing sits on disk longer than it has to.
    background_tasks.add_task(lambda p: Path(p).unlink(missing_ok=True), str(output_path))

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"{safe_company}_report.pdf",
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve the frontend
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
