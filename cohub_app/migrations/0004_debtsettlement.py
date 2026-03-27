from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('cohub_app', '0003_chatmessage'),
    ]

    operations = [
        migrations.CreateModel(
            name='DebtSettlement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Сумма')),
                ('settled_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата погашения')),
                ('from_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='debt_settlements_from', to='auth.user', verbose_name='Кто погасил')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='debt_settlements', to='cohub_app.room', verbose_name='Комната')),
                ('settled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='debt_settlements_done', to='auth.user', verbose_name='Отметил погашение')),
                ('to_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='debt_settlements_to', to='auth.user', verbose_name='Кому погасили')),
            ],
            options={
                'verbose_name': 'Погашение долга',
                'verbose_name_plural': 'История погашений',
                'ordering': ['-settled_at'],
            },
        ),
    ]
