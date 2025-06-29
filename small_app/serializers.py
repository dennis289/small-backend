from rest_framework import serializers
from .models import *

class userSerializer(serializers.ModelSerializer):
    class Meta:
        model= User
        fields = ['id','username','email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
    
class ServiceTimesSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceTimes
        fields = ['id', 'name', 'order']

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'requires_specialization', 'description']

class PersonSerializer(serializers.ModelSerializer):
    roles = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), many=True)

    class Meta:
        model = Person
        fields = ['id', 'user', 'name', 'is_producer', 'roles']
class AvailabilitySerializer(serializers.ModelSerializer):
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all())
    service_time = serializers.PrimaryKeyRelatedField(queryset=ServiceTimes.objects.all())

    class Meta:
        model = Availability
        fields = ['id', 'person', 'date', 'service_time', 'status']

class RosterSerializer(serializers.ModelSerializer):
    producer = PersonSerializer(read_only=True)
    assisstant_producer = PersonSerializer(read_only=True)

    class Meta:
        model = Roster
        fields = ['id', 'date', 'producer', 'assisstant_producer']
    
    def create(self, validated_data):
        producer_data = validated_data.pop('producer')
        assisstant_producer_data = validated_data.pop('assisstant_producer', None)
        producer = Person.objects.get(id=producer_data['id'])
        if assisstant_producer_data:
            assisstant_producer = Person.objects.get(id=assisstant_producer_data['id'])
        else:
            assisstant_producer = None
        roster = Roster.objects.create(
            date=validated_data['date'],
            producer=producer,
            assisstant_producer=assisstant_producer
        )
        return roster
# The serializers above are used to convert model instances into JSON format and vice versa.
# They define how the data should be represented and validated when creating or updating instances.
