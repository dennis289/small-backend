from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import *

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            try:
                user_obj = User.objects.get(email=email)
                user = authenticate(username=user_obj.username, password=password)
                if user:
                    attrs['user'] = user
                    return attrs
                else:
                    raise serializers.ValidationError('Invalid credentials')
            except User.DoesNotExist:
                raise serializers.ValidationError('Invalid credentials')
        else:
            raise serializers.ValidationError('Must include email and password')

class PersonsSerializer(serializers.ModelSerializer):
    roles = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Roles.objects.all(),
        required=False  # Make roles optional
    )
    # For reading (GET), show names
    role_names = serializers.SlugRelatedField(
        many=True,
        read_only=True,
        slug_field='name',
        source='roles'
    )
    # Add full name field for Flutter app compatibility
    name = serializers.SerializerMethodField()
    phone = serializers.CharField(source='phone_number', required=False, allow_blank=True)
    address = serializers.CharField(source='area_of_residence', required=False, allow_blank=True)

    class Meta:
        model = Persons
        fields = [
            'id', 'first_name', 'last_name', 'name', 'email', 'phone_number', 
            'phone', 'area_of_residence', 'address', 'is_producer', 
            'is_assistant_producer', 'is_present', 'roles', 'role_names',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def create(self, validated_data):
        roles_data = validated_data.pop('roles', [])
        person = Persons.objects.create(**validated_data)
        person.roles.set(roles_data)
        return person

    def update(self, instance, validated_data):
        roles_data = validated_data.pop('roles', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if roles_data is not None:
            instance.roles.set(roles_data)
        
        return instance

class RolesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Roles
        fields = ['id', 'name', 'description', 'is_special_role', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

class EventsSerializer(serializers.ModelSerializer):
    # Add duration field for Flutter app compatibility
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = Events
        fields = ['id','name', 'start_time', 'end_time', 'description', 'is_active', 'duration', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']
    
    def get_duration(self, obj):
        # Return duration in minutes - you can customize this logic
        return 60  # Default 60 minutes

class RostersSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source='person.name', read_only=True)
    event_name = serializers.CharField(source='event.name', read_only=True)
    
    class Meta:
        model = Rosters
        fields = ['id', 'person', 'person_name', 'event', 'event_name', 'date', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

class AssignmentSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source='person.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    event_name = serializers.CharField(source='roster.event.name', read_only=True)
    date = serializers.DateField(source='roster.date', read_only=True)
    
    class Meta:
        model = Assignment
        fields = ['id', 'roster', 'person', 'person_name', 'role', 'role_name', 'event_name', 'date']