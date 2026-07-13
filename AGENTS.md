Inspect this Django REST Framework repository.

The project is a image processing API using:
- Django REST Framework
- PostgreSQL
- Redis
- Celery
- MinIO
- Nginx


Core Features:

- Image upload
- Resize images
- Convert PNG/JPEG to WebP
- Generate thumbnails
- Compress images
- Track processing status
- Remove background
- Download processed files

Advanced Features:

- Batch uploads
- Background processing
- Remove image metadata
- Watermarking
- Temporary download links
- Storage quotas
- Automatic file cleanup


First, do not modify any files.

Create a development plan that covers:
1. Recommended Django apps
2. Database models and relationships
3. API endpoints
4. Permissions
5. Background tasks
6. Testing strategy
7. Suggested implementation order

Keep the architecture suitable for a junior backend portfolio project.

Implement the image processing API models.

Requirements:
- Use UUID primary keys
- Every image belongs to the authenticated user
- Include created_at and updated_at
- Use TextChoices for processing status
- Add sensible database indexes
- Create and run migrations
- Add model tests

Do not modify unrelated files.

Create serializers and a ModelViewSet.

Requirements:
- Users can only access their own uploaded images
- Support ordering by created_at and updated_at
- Prevent changing the owner through the API
- Add API tests

Review the current implementation for:
- security problems
- missing validation
- inefficient queries
- broken permissions
- missing tests

Fix confirmed issues only and explain each change.

Create a nice looking frontend that handles all the functionality.