from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    pass
class ServiceTimes(models.Model):
    name= models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0, unique=True)
    def __str__(self):
        return self.name
class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    requires_specialization = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)
    def __str__(self):
        return self.name
class Person(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    is_producer = models.BooleanField(default=False)
    roles = models.ManyToManyField(Role, blank=True)
    def __str__(self):
        return self.name
class Availability(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('unavailable', 'Unavailable'),
    ]
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField()
    service_time = models.ForeignKey(ServiceTimes, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    def __str__(self):
        return f"{self.person.name} - {self.date} - {self.service_time.name} - {self.status}"
class Roster(models.Model):
    date = models.DateField()
    producer = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='rosters')
    assisstant_producer = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='assistant_rosters', null=True, blank=True)
    def __str__(self):
        return f"Roster for {self.date}"
