from django.core.management.base import BaseCommand, CommandError

from small_app.models import User


class Command(BaseCommand):
    help = (
        "Create a platform superadmin (client=None, is_superuser=True) who can "
        "manage clients via the superadmin console."
    )

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--password', required=True)
        parser.add_argument('--email', default='')

    def handle(self, *args, **options):
        username = options['username']
        if User.objects.filter(username=username).exists():
            raise CommandError(f"A user named '{username}' already exists.")

        user = User.objects.create_superuser(
            username=username,
            email=options['email'],
            password=options['password'],
        )
        # create_superuser sets is_superuser/is_staff; ensure no client so this
        # account is platform-level rather than tenant-scoped.
        user.client = None
        user.save(update_fields=['client'])

        self.stdout.write(self.style.SUCCESS(
            f"Platform admin '{username}' created. Log in and open the superadmin console."
        ))
