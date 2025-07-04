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
    roles = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Roles.objects.all(),
        write_only=True  # For writing (POST/PUT), use primary keys
    )
    # For reading (GET), show names
    role_names = serializers.SlugRelatedField(
        many=True,
        read_only=True,
        slug_field='name',
        source='roles'
    )
    class Meta:
        model = Persons
        fields = ['id', 'first_name', 'last_name', 'email', 'phone_number', 'area_of_residence', 'is_producer', 'roles', 'role_names']

class RolesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Roles
        fields = ['id', 'name', 'description', 'is_special_role']

class ServicesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Services
        fields = ['id', 'name', 'description', 'is_active']
