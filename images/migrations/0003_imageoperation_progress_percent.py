from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("images", "0002_remove_imageoperation_op_id_owner_unique_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="imageoperation",
            name="progress_percent",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
            ),
        ),
    ]
