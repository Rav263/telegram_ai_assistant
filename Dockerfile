FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/sh appuser \
    && mkdir -p /var/lib/telegram-ai-assistant/sessions \
    && chown -R appuser:appuser /var/lib/telegram-ai-assistant
USER appuser

CMD ["telegram-ai-assistant", "run", "listener"]
