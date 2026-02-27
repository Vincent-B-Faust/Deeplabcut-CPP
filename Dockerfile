FROM python:3.10-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       libgl1 \
       libglib2.0-0 \
       libsm6 \
       libxext6 \
       libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements ./requirements
COPY pyproject.toml README.md ./
COPY cpp_dlc_live ./cpp_dlc_live
COPY config ./config
COPY tests ./tests

ARG INSTALL_PROFILE=base
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements/${INSTALL_PROFILE}.txt \
    && pip install -e .

CMD ["python", "-m", "cpp_dlc_live.cli", "--help"]
