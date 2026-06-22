from django.db import migrations


# Models that carry a tenant (client) FK and need backfilling.
TENANT_MODELS = [
    'Persons', 'Roles', 'Events', 'Rosters', 'Assignment', 'AwardType',
    'Award', 'RosterFeedback', 'MemberStreak', 'FeedbackShareLink',
    'MembersBulkUpload',
]


def backfill(apps, schema_editor):
    """Assign all pre-existing data and users to a single 'Default' client.

    This preserves the current single-tenant behaviour: existing logins keep
    working, now scoped to the Default client. A separate platform superadmin
    (client=None, is_superuser=True) is created later for cross-client management.
    """
    Client = apps.get_model('small_app', 'Client')
    User = apps.get_model('small_app', 'User')

    models = [apps.get_model('small_app', name) for name in TENANT_MODELS]

    has_data = User.objects.exists() or any(m.objects.exists() for m in models)
    if not has_data:
        # Fresh database — nothing to migrate, don't create an empty default.
        return

    client, _ = Client.objects.get_or_create(
        slug='default', defaults={'name': 'Default'}
    )

    for model in models:
        model.objects.filter(client__isnull=True).update(client=client)

    User.objects.filter(client__isnull=True).update(client=client)


def unbackfill(apps, schema_editor):
    """Reverse: detach everything from the Default client (best effort)."""
    Client = apps.get_model('small_app', 'Client')
    User = apps.get_model('small_app', 'User')

    try:
        client = Client.objects.get(slug='default')
    except Client.DoesNotExist:
        return

    for name in TENANT_MODELS:
        apps.get_model('small_app', name).objects.filter(client=client).update(client=None)
    User.objects.filter(client=client).update(client=None)


class Migration(migrations.Migration):

    dependencies = [
        ('small_app', '0024_client_assignment_client_award_client_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
