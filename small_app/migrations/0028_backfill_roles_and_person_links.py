"""Backfill the tenant role and the person↔login link.

Two independent backfills, both deliberately conservative:

1. **Roles.** Every pre-existing tenant user becomes an ``admin``. Before roles
   existed, any authenticated user could do anything within their client, so
   admin is the only value that preserves what people could already do. Demoting
   anyone is a decision for a human, not a migration.

2. **Person links.** Where a login and a person in the *same client* share an
   email address, they're linked. Matching is case-insensitive. Anything
   ambiguous (an email held by several persons, or several users) is skipped —
   a wrong link would show someone another person's assignments.

Platform superadmins (client=None) are left alone; ``role`` is meaningless for
them.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model('small_app', 'User')
    Persons = apps.get_model('small_app', 'Persons')

    # 1. Existing tenant users keep the access they already had.
    User.objects.filter(client__isnull=False).update(role='admin')

    # 2. Link person -> user on a unique, case-insensitive email match per client.
    users_by_client_email = {}
    ambiguous_users = set()
    for user in User.objects.filter(client__isnull=False).exclude(email=''):
        key = (user.client_id, user.email.strip().lower())
        if key in users_by_client_email:
            ambiguous_users.add(key)
        else:
            users_by_client_email[key] = user.id

    persons_by_key = {}
    ambiguous_persons = set()
    for person in Persons.objects.exclude(email=''):
        key = (person.client_id, (person.email or '').strip().lower())
        if key in persons_by_key:
            ambiguous_persons.add(key)
        else:
            persons_by_key[key] = person

    taken_user_ids = set()
    for key, person in persons_by_key.items():
        if key in ambiguous_persons or key in ambiguous_users:
            continue
        user_id = users_by_client_email.get(key)
        if user_id is None or user_id in taken_user_ids:
            continue
        person.user_id = user_id
        person.save(update_fields=['user'])
        taken_user_ids.add(user_id)


def unbackfill(apps, schema_editor):
    """Drop the links again. Roles are left as they are — reversing them would
    be guesswork, and the column is removed by the schema migration anyway."""
    Persons = apps.get_model('small_app', 'Persons')
    Persons.objects.exclude(user__isnull=True).update(user=None)


class Migration(migrations.Migration):

    dependencies = [
        ('small_app', '0027_persons_user_user_role'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
