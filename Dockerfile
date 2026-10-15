FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Source first, then install, so the package itself is what gets built.
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[ai,robo]" tzdata

# Example configs ship with the image; the real config/ directory is bind-mounted.
COPY config ./config
RUN mkdir -p data logs && chown -R app:app /app
USER app

CMD ["investment-data", "serve"]
