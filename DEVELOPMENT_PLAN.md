# Image Processing API development plan

## Architecture and Django apps

Keep the portfolio project intentionally small:

- `images`: uploaded images, processing operations, quotas, temporary links, API, Celery tasks, and the dashboard.
- Django `auth`: users, session login for the dashboard, and token authentication for API clients.
- Project package: environment-aware PostgreSQL/MinIO/Redis configuration and Celery bootstrap.

Splitting storage, jobs, and uploads into separate apps would add indirection without teaching much at this size. They can be extracted later if those domains grow.

## Models and relationships

- `User 1 -> many UploadedImage`: immutable owner, original object, validated media metadata, processing status, expiry, timestamps.
- `UploadedImage 1 -> many ImageOperation`: resize, WebP, thumbnail, compression, background removal, metadata removal, or watermark parameters and one result object.
- `User 1 -> 1 StorageQuota`: cached byte use and configurable byte limit.
- `ImageOperation 1 -> many TemporaryDownload`: expiring, revocable, limited-use opaque links.

UUID primary keys, ownership/status/time composite indexes, expiry indexes, and database constraints keep normal list, worker, and cleanup paths efficient.

## API endpoints

- `POST /api/auth/register/`, `POST /api/auth/token/`, `POST /api/auth/logout/`
- `GET|POST /api/images/`, `GET|PATCH|DELETE /api/images/{id}/`
- `POST /api/images/batch/`
- `POST /api/images/{id}/process/`
- `GET /api/images/{id}/operations/`
- `POST /api/operations/{id}/temporary-link/`
- `GET /api/operations/{id}/download/`
- `GET /downloads/{token}/` for the time-limited link
- `GET /api/quota/`

Image lists support `?ordering=created_at`, `-created_at`, `updated_at`, and `-updated_at`.

## Permissions and validation

All API routes except registration, token login, and a valid temporary link require authentication. Viewsets filter at the queryset level by `request.user`; related operation lookups are also owner-scoped. Owner, status, storage keys, sizes, errors, and timestamps are read-only. Uploads are checked by decoded image content, allow-listed format, byte limit, pixel limit, and quota—not by filename or client MIME type alone. Processing parameters have bounded dimensions, quality, thumbnail size, and watermark length.

## Background tasks

- `process_image_operation`: decode safely, resize/thumbnail, compress, convert, strip metadata, watermark, optionally remove a background when the optional `rembg` package is installed, save the result, and atomically update status/accounting.
- `cleanup_expired_images`: periodically delete expired originals/results and stale download links.
- `recalculate_storage_quota`: repair cached quota totals.

Redis is the Celery broker/result backend. MinIO is configured through the S3 storage backend. Local filesystem storage and eager Celery execution remain available for a simple local demo and tests.

## Testing strategy

- Model tests: UUID keys, defaults, relationships, constraints, expiry, and quota calculations.
- Serializer tests: real image validation, hostile extensions/content, parameter boundaries, and immutable ownership.
- API tests: authentication, cross-user isolation, ordering, batch upload, quota enforcement, processing, download ownership, temporary-link expiry, and deletion accounting.
- Task tests: Pillow transformations, status transitions, output metadata/format/dimensions, failures, and cleanup.
- Framework checks and migration drift checks in CI; PostgreSQL/Redis/MinIO integration tests in Docker in addition to fast SQLite unit tests.

## Suggested implementation order

1. Environment-safe settings and dependencies.
2. Models, constraints, migrations, and admin.
3. Upload/operation validation and owner-scoped serializers/viewsets.
4. Celery processing and cleanup tasks.
5. Download and quota flows.
6. Dashboard frontend.
7. Model, API, task, and security regression tests.
8. Docker services and Nginx deployment configuration.
