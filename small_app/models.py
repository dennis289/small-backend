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
    # A user with client=None is a platform-level account (superadmin) who can
    # manage clients across the board. Everyone else belongs to one client.
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=True, blank=True,
        related_name='users',
    )

    @property
    def is_platform_admin(self):
        """Platform superadmin: no client and Django superuser."""
        return self.client_id is None and self.is_superuser


class Persons(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='persons'
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
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='roles'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_special_role = models.BooleanField(default=False)
    max_assignments = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['client', 'name'],
                name='unique_role_name_per_client'
            )
        ]

    def __str__(self):
        return self.name or "Unnamed Service"

class Events(models.Model):
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
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, null=False, blank=True, related_name='assignments'
    )
    roster = models.ForeignKey(Rosters,on_delete=models.CASCADE, related_name="assignments")
    role = models.ForeignKey(Roles, on_delete=models.CASCADE)
    person = models.ForeignKey(Persons, on_delete=models.CASCADE)

    class Meta:
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
        ('excellent', 'Excellent Service'),
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
    """Tracks consecutive attendance streaks per person."""
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
