# PixelForge image processing API

A junior-friendly Django REST Framework portfolio project with private image uploads, Celery processing, PostgreSQL, Redis, MinIO, expiring downloads, quota accounting, cleanup, and a responsive server-rendered dashboard.

## Features

- Single and batch PNG/JPEG upload with decoded-content, size, pixel, extension, and quota validation.
- Resize, proportional resize, thumbnail, WebP conversion, compression, metadata stripping, watermarking, and selectable BiRefNet/IS-Net background removal with edge refinement.
- Owner-scoped API queries, previews, operations, and permanent downloads.
- UUID identifiers and opaque expiring, limited-use public download links.
- Processing status/error tracking and automatic expired-file cleanup.
- PostgreSQL indexes, Redis/Celery jobs, private MinIO objects, and Nginx reverse proxy.

The architecture and implementation sequence are documented in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## Run locally (simple mode)

The checked-in `.env` supplies the existing PostgreSQL credentials. For a dependency-free database demo, use SQLite and eager task execution:

```powershell
$env:USE_SQLITE="true"
$env:CELERY_TASK_ALWAYS_EAGER="true"
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Open `http://127.0.0.1:8000/register/`. Background removal downloads its model on first use; other operations work immediately.

Every operation is preserved as its own output and appears beside the untouched source in **Your images**. Background removal defaults to `birefnet-general`; choose the portrait model for people and hair, IS-Net for anime artwork, or the lite model when speed matters more than edge detail. Worker processes reuse loaded model sessions to avoid paying model initialization cost for every job.

## Run the complete stack

Set a strong `SECRET_KEY` and matching database values in `.env`, then run:

```text
docker compose up --build
```

Open `http://localhost:8080`. MinIO's optional console is internal by default; expose port 9001 only for local debugging. Uploaded objects remain private and are streamed through owner-checked Django endpoints.

For an internet deployment, terminate TLS at Nginx or a load balancer, pass `X-Forwarded-Proto`, and set `SECURE_SSL_REDIRECT=true`, `SECURE_COOKIES=true`, and an appropriate `SECURE_HSTS_SECONDS`. HSTS defaults to off because enabling it on a local HTTP host can lock browsers out.

## API examples

Obtain a token:

```text
POST /api/auth/token/  {"username":"alice","password":"..."}
Authorization: Token <token>
```

Key routes are `/api/images/`, `/api/images/batch/`, `/api/images/{id}/process/`, `/api/operations/{id}/download/`, `/api/operations/{id}/temporary-link/`, and `/api/quota/`. Supported ordering values are `created_at`, `-created_at`, `updated_at`, and `-updated_at`.

## Tests

```powershell
$env:USE_SQLITE="true"
.\.venv\Scripts\python.exe manage.py test images
.\.venv\Scripts\python.exe manage.py check --deploy
```

The fast suite uses SQLite and local temporary storage. Add service-level integration tests against the Compose stack in CI to validate PostgreSQL, Redis, and MinIO wiring.
