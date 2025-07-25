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
    roles = models.ManyToManyField('Roles', blank=True)  # Changed to ManyToManyField
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
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

