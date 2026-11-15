FROM python:3.12-slim
WORKDIR /srv
# Tesseract reads the text on invoice photos.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml alembic.ini ./
COPY app app
COPY migrations migrations
RUN pip install --no-cache-dir .
RUN useradd --system api
USER api
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
