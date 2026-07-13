FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN addgroup --system django && adduser --system --ingroup django django \
    && mkdir -p /app/staticfiles /app/media /home/django/.u2net \
    && chown -R django:django /app /home/django

USER django

CMD ["gunicorn", "Image_processing_API.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
