from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    pass


class Persons(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    area_of_residence = models.TextField(blank=True, null=True)
    is_producer = models.BooleanField(default=False)
    is_assistant_producer = models.BooleanField(default=False)
    is_present = models.BooleanField(default=True, null=False, blank=False)
    is_active = models.BooleanField(default=True)
    roles = models.ManyToManyField('Roles', blank=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Roles(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_special_role = models.BooleanField(default=False)
    max_assignments = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.name or "Unnamed Service"

class Events(models.Model):
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
    event = models.ForeignKey(Events, on_delete=models.CASCADE, null=True)
    date = models.DateField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('event', 'date')

    def __str__(self):
        return f"{self.event} - {self.date}"
    
class Assignment(models.Model):
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
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Award(models.Model):
    """Recognition record — a person, an award type, and the streak it ended."""
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

    roster = models.ForeignKey(
        Rosters, on_delete=models.CASCADE, related_name='feedback'
    )
    person = models.ForeignKey(
        Persons, on_delete=models.CASCADE, related_name='feedback'
    )
    is_present = models.BooleanField(default=False)
    feedback = models.TextField(blank=True, null=True)
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
    token = models.CharField(max_length=64, unique=True, db_index=True)
    date = models.DateField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    global_feedback = models.TextField(blank=True, null=True)
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
    json_data = models.JSONField()
    status = models.BooleanField(default=False)
    number_of_records = models.IntegerField(default=0)
    success_products = models.IntegerField(default=0)
    failed_products = models.IntegerField(default=0)
    created_at = models.DateField(auto_now_add=True)
    updated_at = models.DateField(auto_now=True)
    
