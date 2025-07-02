from rest_framework import serializers
from .models import *

class userSerializer(serializers.ModelSerializer):
    class Meta:
        model= User
        fields = ['id','username','email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

class PersonsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Persons
        fields = ['id', 'first_name', 'last_name', 'email', 'phone_number', 'area_of_residence', 'is_producer', 'role']

class RolesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Roles
        fields = ['id', 'name', 'description']
