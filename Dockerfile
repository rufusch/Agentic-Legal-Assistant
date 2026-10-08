FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 BACKEND_STORAGE=/data BACKEND_DEMO=0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 fonts-dejavu-core antiword && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY --chown=app:app backend backend
COPY --chown=app:app frontend frontend
COPY --chown=app:app antigravity-frontend antigravity-frontend
COPY --chown=app:app hacknex2-frontend hacknex2-frontend
COPY --chown=app:app corpus corpus
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
