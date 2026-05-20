from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cohub_app', '0007_userprofile_mood_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='is_shared',
            field=models.BooleanField(default=False, verbose_name='Общий расход'),
        ),
    ]
