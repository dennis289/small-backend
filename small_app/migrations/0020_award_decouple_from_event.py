import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_given_at(apps, schema_editor):
    Award = apps.get_model('small_app', 'Award')
    for award in Award.objects.all():
        award.given_at = award.created_at.date()
        award.save(update_fields=['given_at'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('small_app', '0019_rosterfeedback_feedback_category_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Add the new fields. given_at is nullable for the backfill step.
        migrations.AddField(
            model_name='award',
            name='given_at',
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name='award',
            name='streak_at_award',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='award',
            name='given_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='awards_given',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # 2. Backfill given_at from created_at.
        migrations.RunPython(backfill_given_at, noop_reverse),

        # 3. Enforce non-null on given_at now that every row has a value.
        migrations.AlterField(
            model_name='award',
            name='given_at',
            field=models.DateField(),
        ),

        # 4. Drop the event FK (and the OneToOne uniqueness it carried).
        migrations.RemoveField(
            model_name='award',
            name='event',
        ),

        # 5. Loosen the award_type on_delete to PROTECT to match the model.
        migrations.AlterField(
            model_name='award',
            name='award_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='awards',
                to='small_app.awardtype',
            ),
        ),

        # 6. Ordering + indexes.
        migrations.AlterModelOptions(
            name='award',
            options={'ordering': ['-given_at', '-created_at']},
        ),
        migrations.AddIndex(
            model_name='award',
            index=models.Index(fields=['-given_at'], name='small_app_a_given_a_944d1e_idx'),
        ),
        migrations.AddIndex(
            model_name='award',
            index=models.Index(fields=['person'], name='small_app_a_person__6013f7_idx'),
        ),
    ]
