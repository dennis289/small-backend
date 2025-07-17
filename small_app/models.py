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
    is_assistant_producer= models.BooleanField(default= False)
    is_present = models.BooleanField(default=True, null=False, blank=False)
    roles = models.ManyToManyField('Roles', blank=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Roles(models.Model):
    name=models.CharField(max_length=100, unique=True)
    description=models.TextField(blank=True, null=True)
    is_special_role = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.name

class Services(models.Model):
    time = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.time
    
class Rosters(models.Model):
    person = models.ForeignKey(Persons, on_delete=models.CASCADE)
    service = models.ForeignKey(Services, on_delete=models.CASCADE)
    date = models.DateField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('person', 'service')

    def __str__(self):
        return f"{self.person} - {self.service}"
    
class Assignment(models.Model):
    roster = models.ForeignKey(Rosters,on_delete=models.CASCADE, related_name="assignments")
    role = models.ForeignKey(Roles, on_delete=models.CASCADE)
    person = models.ForeignKey(Persons, on_delete=models.CASCADE)

    class Meta:

        constraints =[
            models.UniqueConstraint(
                fields=['person','roster'],
                name='unique_assignment_per_person_per_service'
            )
        ]

    def __str__(self):
        return f"{self.person} _ {self.role} on {self.roster.service.name} ({self.roster.date})"
