FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 fonts-dejavu-core antiword \
    && rm -rf /var/lib/apt/lists/*
