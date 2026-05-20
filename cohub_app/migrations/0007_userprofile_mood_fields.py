from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cohub_app', '0006_taskreassignmentrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='mood_key',
            field=models.CharField(blank=True, default='calm', max_length=20, verbose_name='Текущее настроение'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='mood_note',
            field=models.CharField(blank=True, max_length=120, verbose_name='Короткая заметка к настроению'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='mood_updated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Когда обновили настроение'),
        ),
    ]
