# PotatoHQ — one container for the whole hangout (API + WebSockets + frontend).
# SQLite lives in /app/data; mount it as a volume so accounts survive.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY web ./web
COPY run.py .

ENV POTATO_HOST=0.0.0.0 \
    POTATO_PORT=8420

EXPOSE 8420
VOLUME ["/app/data"]

CMD ["python", "run.py"]
