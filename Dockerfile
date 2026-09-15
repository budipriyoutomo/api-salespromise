FROM python:3.11-slim

# Set env
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set workdir
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# 🔒 Create non-root user
RUN useradd -m appuser

# ✅ FIX permission
RUN mkdir -p logs && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 🗄️ Migrasi dulu (sekali, sebelum worker lahir), baru Gunicorn + Uvicorn worker.
# Kalau migrasi gagal, container berhenti — tidak melayani request di atas skema setengah jadi.
# Dijalankan saat start, bukan build: saat build database tidak terjangkau.
CMD ["sh", "-c", "python migrate.py && exec gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000 --workers 4"]