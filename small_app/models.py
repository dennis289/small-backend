"""Domain models for the roster/scheduling app.

Everything here is multi-tenant: every row carries a ``client`` FK and views read
through ``small_app.views.scoped()`` so data never crosses tenant boundaries.
The one exception is ``User``, where ``client=None`` marks a platform superadmin.

Rough shape of the domain:

    Client ─┬─ User            login accounts
            ├─ Persons         team members who get scheduled
            ├─ Roles           jobs a person can be assigned to
            ├─ Events          recurring slots to be staffed, each bound to Roles
            ├─ Rosters         one (Event, date) pairing
            │   └─ Assignment  (Roster, Role, Person)
            ├─ AwardType / Award
            ├─ RosterFeedback / MemberStreak
            └─ FeedbackShareLink
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Client(models.Model):
    """A tenant — one customer organisation. All domain data is scoped to a
    client, and every (non-platform) user belongs to exactly one client."""
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    """A login account.

    Two tiers, distinguished by whether ``client`` is set:

    * ``client=None`` + ``is_superuser`` — platform superadmin. Manages clients
      (tenants) but owns no tenant data; ``role`` is meaningless for them.
    * ``client`` set — a tenant user, whose ``role`` decides what they may do
      inside that client. See the ROLE_* constants.

    A tenant user is not the same thing as a ``Persons`` row: users log in,
    persons get scheduled. ``Persons.user`` optionally links the two so a member
    can be shown their own assignments.
    """

    ROLE_ADMIN = 'admin'
    ROLE_SCHEDULER = 'scheduler'
    ROLE_MEMBER = 'member'

    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),          # everything within the client, incl. users
        (ROLE_SCHEDULER, 'Scheduler'),  # builds rosters and records attendance
        (ROLE_MEMBER, 'Member'),        # read-only view of published rosters
    ]

    # A user with client=None is a platform-level account (superadmin) who can
    # manage clients across the board. Everyone else belongs to one client.
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=True, blank=True,
        related_name='users',
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default=ROLE_ADMIN,
        help_text='What this user may do within their client.',
    )

    @property
    def is_platform_admin(self):
        """Platform superadmin: no client and Django superuser."""
        return self.client_id is None and self.is_superuser

    @property
    def is_client_admin(self):
        """Admin of their own client — full access to that client's data and users."""
        return self.client_id is not None and self.role == self.ROLE_ADMIN

    @property
    def can_schedule(self):
        """May build rosters and record attendance (admins and schedulers)."""
        return self.client_id is not None and self.role in (
            self.ROLE_ADMIN, self.ROLE_SCHEDULER,
        )


class Persons(models.Model):
    """A schedulable team member (not a login account — see ``User`` for that).

    ``is_active`` is the persistent "still on the team" flag; ``is_present`` is the
    persistent "available to be scheduled" flag. Both must be true for the generator
    to consider someone. A one-off absence is passed to the generator as
    ``absent_members`` instead, which excludes the person without touching either flag.

    ``is_producer`` / ``is_assistant_producer`` mark eligibility for the two
    leadership slots, which are picked separately from the ``roles`` M2M.

    ``user`` optionally links this person to a login, which is what lets a member
    see their own assignments highlighted. It is nullable and expected to stay
    null for most people: plenty of people are scheduled without ever logging in.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='persons'
    )
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='person',
        help_text="Login belonging to this person, if they have one.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    area_of_residence = models.TextField(blank=True, null=True)
    is_producer = models.BooleanField(default=False)
    is_assistant_producer = models.BooleanField(default=False)
    is_present = models.BooleanField(default=True, null=False, blank=False)
    is_active = models.BooleanField(default=True)
    roles = models.ManyToManyField('Roles', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['client', 'email'],
                name='unique_person_email_per_client'
            )
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Roles(models.Model):
    """A job a person can be assigned to (e.g. Camera, Sound, Ushering).

    ``is_special_role`` splits the two ways a role gets filled:
      * normal roles are filled once per Event they're bound to;
      * special roles are filled once per roster date, across all events, and may
        take up to ``max_assignments`` people.

    Role names are matched case-insensitively throughout the generator, so treat
    the name as the role's real identity.

    ``is_active`` takes a role out of *future* generation runs without deleting it.
    Rosters already saved keep their assignments and still render the role, so past
    PDFs reproduce unchanged — see ``RosterGenerator.generate``.

    ``display_order`` is the order roles appear in, on screen and in the exported
    PDF. It's the default Meta ordering, so every queryset — including
    ``event.roles.all()`` — comes out in the arrangement the admin chose, and the
    PDF inherits it for free because it renders the payload in the order given.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='roles'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_special_role = models.BooleanField(default=False)
    max_assignments = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive roles are skipped when generating new rosters.',
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text='Position in the roster and PDF. Lower comes first.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Name breaks ties so the order is total, and stays stable across requests
        # while several roles still share the default display_order of 0.
        ordering = ['display_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['client', 'name'],
                name='unique_role_name_per_client'
            )
        ]

    def __str__(self):
        return self.name or "Unnamed Role"

class Events(models.Model):
    """A recurring slot to be staffed (e.g. "Morning Session", "Midweek").

    An Event is a template, not a dated occurrence — pairing it with a date
    produces a ``Rosters`` row.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='events'
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    # Roles required for this event. The roster generator only fills these roles
    # for this event; an event with no roles produces no assignments.
    roles = models.ManyToManyField('Roles', blank=True, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or "Unnamed Event"

class Rosters(models.Model):
    """One Event on one date — the container its Assignments hang off.

    A single calendar day usually has several Rosters (one per active Event).
    Leadership and special-role assignments are all stored against the *first*
    roster of the day; see ``RosterGenerator.save_roster_to_database``.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='rosters'
    )
    event = models.ForeignKey(Events, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'date')

    def __str__(self):
        return f"{self.event} - {self.date}"

class Assignment(models.Model):
    """A person doing a role on a roster. This table *is* the assignment history
    the generator reads to work out rotation, cooldowns and fairness scores.

    ``display_order`` records the arrangement the scheduler dragged the rows into
    before saving, so reopening the date reproduces their layout — and therefore
    their PDF — rather than falling back to the roles' default order.

    Leadership and special roles are day-level but still need a roster to hang off,
    so they are stored against the first roster of the day alongside that event's
    own assignments. To keep the three groups from interleaving, each is written
    into its own band of the number line; see ``ORDER_BAND_*`` below.
    """

    # Bands keep event rows, leadership and special roles separately ordered even
    # though they share one roster's assignment set.
    ORDER_BAND_EVENT = 0
    ORDER_BAND_LEADERSHIP = 1000
    ORDER_BAND_SPECIAL = 2000

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='assignments'
    )
    roster = models.ForeignKey(Rosters,on_delete=models.CASCADE, related_name="assignments")
    role = models.ForeignKey(Roles, on_delete=models.CASCADE)
    person = models.ForeignKey(Persons, on_delete=models.CASCADE)
    display_order = models.PositiveIntegerField(
        default=0,
        help_text='Saved row position within its band. Lower comes first.',
    )

    class Meta:
        # id breaks ties so the order is total for rows saved before this column
        # existed, which all share the default 0.
        ordering = ['display_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['person','roster','role'],
                name='unique_assignment_per_person_per_role_per_roster'
            )
        ]

    def __str__(self):
        return f"{self.person} _ {self.role} on {self.roster.event.name} ({self.roster.date})"

class AwardType(models.Model):
    """Dynamic list of award types (e.g. Day off, Appreciation email, Gift)."""
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='award_types'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['client', 'name'],
                name='unique_award_type_name_per_client'
            )
        ]

    def __str__(self):
        return self.name


class Award(models.Model):
    """Recognition record — a person, an award type, and the streak it ended."""
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='awards'
    )
    person = models.ForeignKey(
        Persons, on_delete=models.CASCADE, related_name='awards'
    )
    award_type = models.ForeignKey(
        AwardType, on_delete=models.PROTECT, related_name='awards'
    )
    given_at = models.DateField()
    streak_at_award = models.PositiveIntegerField(default=0)
    given_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='awards_given',
    )
    feedback = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-given_at', '-created_at']
        indexes = [
            models.Index(fields=['-given_at']),
            models.Index(fields=['person']),
        ]

    def __str__(self):
        return f"{self.award_type} → {self.person} ({self.given_at})"


class RosterFeedback(models.Model):
    """Per-person feedback for a roster – tracks presence and comments."""

    CATEGORY_CHOICES = [
        ('general', 'General'),
        ('punctuality', 'Punctuality'),
        ('teamwork', 'Teamwork'),
        ('performance', 'Performance'),
        ('attitude', 'Attitude'),
        ('excellent', 'Excellence'),
    ]

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='roster_feedback'
    )
    roster = models.ForeignKey(
        Rosters, on_delete=models.CASCADE, related_name='feedback'
    )
    person = models.ForeignKey(
        Persons, on_delete=models.CASCADE, related_name='feedback'
    )
    is_present = models.BooleanField(default=False)
    feedback = models.TextField(blank=True, null=True)
    recommendations = models.TextField(blank=True, null=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback_category = models.CharField(
        max_length=50, blank=True, null=True, choices=CATEGORY_CHOICES
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['roster', 'person'],
                name='unique_feedback_per_person_per_roster'
            )
        ]

    def __str__(self):
        status = "Present" if self.is_present else "Absent"
        return f"{self.person} – {status} ({self.roster})"


class MemberStreak(models.Model):
    """Consecutive-attendance streak per person, derived from RosterFeedback.

    Recomputed by ``small_app.views._recalculate_streak`` whenever feedback is
    submitted. Counts **event days**, not feedback rows: a day with three events
    adds one, and only if the person was present at all three. Attendance dated on or
    before the person's most recent award is excluded, so granting an award really
    does start them over.
    """
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='member_streaks'
    )
    person = models.OneToOneField(
        Persons, on_delete=models.CASCADE, related_name='streak'
    )
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.person} — streak: {self.current_streak}"


class FeedbackShareLink(models.Model):
    """A one-time-use shareable link for collecting feedback for a roster date.

    The token is unguessable and unauthenticated — anyone with the URL can submit
    once. After submission, ``is_used`` flips to True and the form rejects further
    posts. ``global_feedback`` stores the single overall note attached to the form.
    """
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='feedback_links'
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    date = models.DateField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    global_feedback = models.TextField(blank=True, null=True)
    global_recommendations = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='feedback_links_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "used" if self.is_used else "open"
        return f"FeedbackShareLink({self.date}, {status})"


class MembersBulkUpload(models.Model):
    """Audit row for a CSV/JSON member import — stores the raw payload plus counts.

    Written by ``small_app.views.bulk_upload_persons``. ``json_data`` is the exact
    list of records that was posted, so a failed import can be replayed or diffed.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='bulk_uploads'
    )
    json_data = models.JSONField()
    status = models.BooleanField(default=False)
    number_of_records = models.IntegerField(default=0)
    success_products = models.IntegerField(default=0)
    failed_products = models.IntegerField(default=0)
    created_at = models.DateField(auto_now_add=True)
    updated_at = models.DateField(auto_now=True)
