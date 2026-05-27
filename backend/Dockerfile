FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

COPY . .

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "trivia.asgi:application"]

