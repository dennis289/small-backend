from django.core.management.base import BaseCommand, CommandError

from small_app.models import Client, User


class Command(BaseCommand):
    help = (
        "Create (or repoint) a throwaway account for exercising the password-reset "
        "email flow. Give it an inbox you can actually read: 'forgot password' then "
        "delivers a real link there."
    )

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True, help='Inbox that should receive the reset link.')
        parser.add_argument('--username', default='resettest')
        parser.add_argument('--password', default='ResetTest!2024')
        parser.add_argument(
            '--client', type=int, default=None,
            help='Client id to attach to. Defaults to the only client, if there is exactly one.',
        )

    def handle(self, *args, **options):
        client_id = options['client']
        if client_id is None:
            clients = list(Client.objects.all()[:2])
            if len(clients) != 1:
                raise CommandError(
                    'Pass --client <id>: there is no single obvious client to attach to.'
                )
            client = clients[0]
        else:
            try:
                client = Client.objects.get(pk=client_id)
            except Client.DoesNotExist:
                raise CommandError(f'No client with id {client_id}.')

        username = options['username']
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'client': client, 'role': User.ROLE_ADMIN},
        )
        # Rerunning with a different --email just repoints the same account, so
        # the test can be aimed at another inbox without piling up users.
        user.email = options['email']
        user.client = client
        user.is_active = True
        user.set_password(options['password'])
        user.save()

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} '{username}' "
            f"<{user.email}> on client '{client.name}'. "
            f"Password: {options['password']}"
        ))
