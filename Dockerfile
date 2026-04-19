FROM python:3.11-slim

WORKDIR /app

# Runtime deps only (PyMuPDF ships its own MuPDF wheels — no libmupdf-dev needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download FastEmbed model so it's available at runtime
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('intfloat/multilingual-e5-large')" || true

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
