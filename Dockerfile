FROM python:3.12-slim-bookworm

# System libraries WeasyPrint needs to render PDFs (this is the Linux
# equivalent of the GTK runtime we had to install separately on Windows -
# here it's baked into the image once, so it always just works).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY templates/ templates/

WORKDIR /app/backend

# Render sets $PORT at runtime; default to 8000 for local docker testing.
ENV PORT=8000
CMD uvicorn main:app --host 0.0.0.0 --port $PORT