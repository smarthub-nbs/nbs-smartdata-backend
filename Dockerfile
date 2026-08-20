FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN useradd -m -u 1000 appuser

WORKDIR /app/src

RUN pip install --no-cache-dir uv

COPY src/pyproject.toml src/uv.lock ./
RUN uv sync --frozen

COPY src/ ./

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import http.client; http.client.HTTPConnection('localhost', 8000).request('GET', '/health'); exit(0)" || exit(1)

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
