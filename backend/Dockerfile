FROM python:3.12-slim

# Faster, smaller, no .pyc files cluttering the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly mounts the persistent volume at /data — the SQLite file lives there
# so donor records survive restarts and redeploys.
ENV DB_PATH=/data/donors.db

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
