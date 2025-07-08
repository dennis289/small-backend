from django.shortcuts import render
from .serializers import *
from .models import *
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .scheduler import generate_roster
from datetime import datetime


User = get_user_model()

# Create your views here.

# signing up users to the system
@api_view(['POST'])
def signup(request):
    if request.method == 'POST':
        serializer = userSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    else:
        return Response({"error": "method not allowed"}, status=405)
    
@api_view(['POST'])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({"error": "Missing email or password"}, status=status.HTTP_400_BAD_REQUEST)
    print(email, password)
    try:
        user_obj = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(username=user_obj.username, password=password)
    if user:
        tokens = get_tokens_for_user(user)  # Generate tokens for the user
        return Response({
            "message": "Login successful",
            "email": user.email,
            "username": user.username,
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

@api_view(['POST','GET','PUT','DELETE'])
def persons(request):
    if request.method == 'POST':
        serializer = PersonsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        persons = Persons.objects.all()
        serializer = PersonsSerializer(persons, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        person_id = request.data.get('id')
        try:
            person = Persons.objects.get(id=person_id)
        except Persons.DoesNotExist:
            return Response({"error": "Person not found"}, status=404)
        
        serializer = PersonsSerializer(person, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        person_id = request.data.get('id')
        try:
            person = Persons.objects.get(id=person_id)
            person.delete()
            return Response({"message": "Person deleted successfully"}, status=204)
        except Persons.DoesNotExist:
            return Response({"error": "Person not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
@api_view(['GET'])
def person_detail(request, pk):
    try:
        person = Persons.objects.get(pk=pk)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)

    serializer = PersonsSerializer(person)
    return Response(serializer.data, status=200)

@api_view(['POST','GET','PUT','DELETE'])
def roles(request):
    if request.method == 'POST':
        serializer = RolesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        roles = Roles.objects.all()
        serializer = RolesSerializer(roles, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        role_id = request.data.get('id')
        try:
            role = Roles.objects.get(id=role_id)
        except Roles.DoesNotExist:
            return Response({"error": "Role not found"}, status=404)
        
        serializer = RolesSerializer(role, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        role_id = request.data.get('id')
        try:
            role = Roles.objects.get(id=role_id)
            role.delete()
            return Response({"message": "Role deleted successfully"}, status=204)
        except Roles.DoesNotExist:
            return Response({"error": "Role not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
    
@api_view(['GET'])
def role_detail(request, pk):
    try:
        role = Roles.objects.get(pk=pk)
    except Roles.DoesNotExist:
        return Response({"error": "Role not found"}, status=404)

    serializer = RolesSerializer(role)
    return Response(serializer.data, status=200)

@api_view(['POST','GET','PUT','DELETE'])
def services(request):
    if request.method == 'POST':
        serializer = ServicesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        services = Services.objects.all()
        serializer = ServicesSerializer(services, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        service_id = request.data.get('id')
        try:
            service = Services.objects.get(id=service_id)
        except Services.DoesNotExist:
            return Response({"error": "Service not found"}, status=404)
        
        serializer = ServicesSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        service_id = request.data.get('id')
        try:
            service = Services.objects.get(id=service_id)
            service.delete()
            return Response({"message": "Service deleted successfully"}, status=204)
        except Services.DoesNotExist:
            return Response({"error": "Service not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
@api_view(['GET'])
def service_detail(request, pk):
    try:
        service = Services.objects.get(pk=pk)
    except Services.DoesNotExist:
        return Response({"error": "Service not found"}, status=404)

    serializer = ServicesSerializer(service)
    return Response(serializer.data, status=200)

@api_view(['POST','GET','PUT','DELETE'])
def rosters(request):
    if request.method == 'POST':
        date = request.data.get('date')
        if not date:
            return Response({'date': ['This field is required.']}, status=400)
        try:
            # Parse ISO 8601 date if necessary
            try:
                date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                return Response({'date': ['Invalid date format. Must be YYYY-MM-DD.']}, status=400)

            # Generate assignments using your scheduler
            assignments = generate_roster(date)
            # Create the Roster object
            roster = Rosters.objects.create(date=date)
            # Create Assignment objects for this roster
            for a in assignments:
                Assignment.objects.create(
                    roster=roster,
                    person_id=a['person_id'],
                    service_id=a['service_time_id'],
                    role_id=a['role_id']
                )
            serializer = RostersSerializer(roster)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({'error': str(e)}, status=400)
    elif request.method == 'GET':
        rosters = Rosters.objects.all()
        serializer = RostersSerializer(rosters, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        roster_id = request.data.get('id')
        try:
            roster = Rosters.objects.get(id=roster_id)
        except Rosters.DoesNotExist:
            return Response({"error": "Roster not found"}, status=404)
        
        serializer = RostersSerializer(roster, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        roster_id = request.data.get('id')
        try:
            roster = Rosters.objects.get(id=roster_id)
            roster.delete()
            return Response({"message": "Roster deleted successfully"}, status=204)
        except Rosters.DoesNotExist:
            return Response({"error": "Roster not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)

@api_view(['GET'])
def roster_detail(request, pk):
    try:
        roster = Rosters.objects.get(pk=pk)
    except Rosters.DoesNotExist:
        return Response({"error": "Roster not found"}, status=404)

    serializer = RostersSerializer(roster)
    return Response(serializer.data, status=200)

@api_view(['POST','GET','PUT','DELETE'])
def availability(request):
    if request.method == 'POST':
        serializer = AvailabilitySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        availabilities = Availability.objects.all()
        serializer = AvailabilitySerializer(availabilities, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        availability_id = request.data.get('id')
        try:
            availability = Availability.objects.get(id=availability_id)
        except Availability.DoesNotExist:
            return Response({"error": "Availability not found"}, status=404)
        
        serializer = AvailabilitySerializer(availability, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        availability_id = request.data.get('id')
        try:
            availability = Availability.objects.get(id=availability_id)
            availability.delete()
            return Response({"message": "Availability deleted successfully"}, status=204)
        except Availability.DoesNotExist:
            return Response({"error": "Availability not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)



@api_view(['POST','GET','PUT','DELETE'])
def assignments(request):
    if request.method == 'POST':
        serializer = AssignmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        assignments = Assignment.objects.all()
        serializer = AssignmentSerializer(assignments, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        assignment_id = request.data.get('id')
        try:
            assignment = Assignment.objects.get(id=assignment_id)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found"}, status=404)
        
        serializer = AssignmentSerializer(assignment, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        assignment_id = request.data.get('id')
        try:
            assignment = Assignment.objects.get(id=assignment_id)
            assignment.delete()
            return Response({"message": "Assignment deleted successfully"}, status=204)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
    
@api_view(['GET'])
def assignment_detail(request, pk):
    try:
        assignment = Assignment.objects.get(pk=pk)
    except Assignment.DoesNotExist:
        return Response({"error": "Assignment not found"}, status=404)

    serializer = AssignmentSerializer(assignment)
    return Response(serializer.data, status=200)

