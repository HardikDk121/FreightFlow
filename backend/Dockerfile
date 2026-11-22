FROM python:3.12-slim
WORKDIR /srv
# Tesseract reads the text on invoice photos.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml alembic.ini constraints.txt ./
COPY app app
COPY migrations migrations
# Install the exact versions the tests passed with.
RUN pip install --no-cache-dir -c constraints.txt .
RUN useradd --system api
USER api
EXPOSE 8000
# --proxy-headers: behind a reverse proxy (Caddy below, or your own nginx), take the caller's address
# from X-Forwarded-For, but only when the request comes from FF_FORWARDED_ALLOW_IPS. Sign-in limits
# count per address, so this must be right or every caller looks like the proxy.
ENV FF_FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FF_FORWARDED_ALLOW_IPS\" --timeout-keep-alive 15"]
