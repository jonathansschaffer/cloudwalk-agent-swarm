FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed by sentence-transformers and chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── CRITICAL: install PyTorch CPU-only BEFORE other packages ──────────────────
# Without this, pip resolves the full GPU wheel (~750 MB) which causes Railway's
# build to time out. The CPU wheel is ~200 MB and sufficient for inference.
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies (torch is already satisfied — no GPU wheel pulled)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create data directories (chroma_db is committed; scraped_cache is generated)
RUN mkdir -p data/chroma_db data/scraped_cache

EXPOSE 8000

# Give 5 minutes for first start: embedding model downloads (~90 MB) on first use
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# Railway injects $PORT; falls back to 8000 for local runs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
