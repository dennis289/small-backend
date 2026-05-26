from rest_framework import serializers

from .models import (
    User, Persons, Roles, Events, Rosters, Assignment,
    AwardType, Award, RosterFeedback,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class PersonsSerializer(serializers.ModelSerializer):
    roles = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Roles.objects.all(),
        required=False
    )
    role_names = serializers.SlugRelatedField(
        many=True,
        read_only=True,
        slug_field='name',
        source='roles'
    )
    name = serializers.SerializerMethodField()

    class Meta:
        model = Persons
        fields = [
            'id', 'first_name', 'last_name', 'name', 'email', 'phone_number',
            'area_of_residence', 'is_producer', 'is_assistant_producer',
            'is_present', 'is_active', 'roles', 'role_names',
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
        fields = ['id', 'name', 'description', 'is_special_role', 'max_assignments', 'created_at', 'updated_at']
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
    event_name = serializers.CharField(source='event.name', read_only=True)

    class Meta:
        model = Rosters
        fields = ['id', 'event', 'event_name', 'date', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

class AssignmentSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()
    role_name = serializers.CharField(source='role.name', read_only=True)
    event_name = serializers.CharField(source='roster.event.name', read_only=True)
    date = serializers.DateField(source='roster.date', read_only=True)

    class Meta:
        model = Assignment
        fields = ['id', 'roster', 'person', 'person_name', 'role', 'role_name', 'event_name', 'date']

    def get_person_name(self, obj):
        return f"{obj.person.first_name} {obj.person.last_name}".strip()


class AwardTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AwardType
        fields = ['id', 'name', 'description', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class AwardSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()
    award_type_name = serializers.CharField(source='award_type.name', read_only=True)
    given_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Award
        fields = [
            'id', 'person', 'person_name',
            'award_type', 'award_type_name',
            'given_at', 'streak_at_award',
            'given_by', 'given_by_name',
            'feedback', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'streak_at_award', 'given_by', 'given_by_name',
            'created_at', 'updated_at',
        ]

    def get_person_name(self, obj):
        return f"{obj.person.first_name} {obj.person.last_name}".strip()

    def get_given_by_name(self, obj):
        if not obj.given_by:
            return None
        u = obj.given_by
        full = f"{u.first_name} {u.last_name}".strip()
        return full or u.username


class RosterFeedbackSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()
    roster_date = serializers.DateField(source='roster.date', read_only=True)
    event_name = serializers.CharField(source='roster.event.name', read_only=True)

    class Meta:
        model = RosterFeedback
        fields = [
            'id', 'roster', 'roster_date', 'event_name',
            'person', 'person_name', 'is_present', 'feedback',
            'rating', 'feedback_category',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_person_name(self, obj):
        return f"{obj.person.first_name} {obj.person.last_name}".strip()


