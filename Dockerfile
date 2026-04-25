# syntax=docker/dockerfile:1
#
# Python + browsers: use mcr.microsoft.com/playwright/python (not …/playwright:… without /python/,
# which is the Node image). Tag should match the pip package in requirements.txt.
# As of Playwright 1.58, mcr publishes e.g. v1.58.0-noble; there is no playwright/python:v1.58.2-noble
# yet — use v1.58.2-noble only for the Node image, or bump this tag when Microsoft publishes it.

FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend /build/dist /app/frontend/dist

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
