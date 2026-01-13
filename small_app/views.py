import ast
import json
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
from datetime import datetime, date, time
from .pdf import export_roster_pdf  # Now available with reportlab installed
from django.http import HttpResponse



User = get_user_model()

# Create your views here.
def parse_roles(roles):

    if not roles:
        return []

    try:
        return ast.literal_eval(roles)
    except (ValueError, SyntaxError):
        pass

    try:
        return json.loads(roles)
    except (ValueError, TypeError):
        pass
    
    if isinstance(roles, str):
            return [branch.strip() for branch in roles.split(',') if branch.strip()]

    return [roles]

# signing up users to the system
@api_view(['POST'])
def signup(request):
    if request.method == 'POST':
        serializer = UserSerializer(data=request.data)
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

    # ensure either email or username is provided and password is provided
    if not email or not password:
        return Response({"error": "Email and password are required"}, status=status.HTTP_400_BAD_REQUEST)
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

@api_view(['POST','GET'])
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
    
@api_view(['PUT', 'DELETE'])
def modify_person(request,id):
    if request.method == 'PUT':
        person_id = request.data.get('id')
        try:
            person = Persons.objects.get(id=id)
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
            person = Persons.objects.get(id=id)
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

@api_view(['POST'])
def bulk_upload_persons(request):
    """Endpoint to handle bulk upload of persons via CSV file"""
    json_data = request.data.get('data')
    if not json_data:
        return Response({"error": "No data provided"}, status=400)
    number_of_records = len(json_data)
    assortment_bulk_upload = MembersBulkUpload.objects.create(
        json_data=json_data, number_of_records= number_of_records)
    for record in json_data:
        first_name = record.get('first_name')
        last_name = record.get('last_name')
        email = record.get('email')
        phone_number = record.get('contact')
        area_of_residence = record.get('area_of_residence')
        is_producer = record.get('is_producer', False)
        is_assistant_producer = record.get('is_assistant_producer', False)
        is_active = record.get('is_active', True)
        roles = record.get('roles', [])

        if first_name == None or first_name == "":
            print("Skipping record due to missing first name")
            continue
        if last_name == None or last_name == "":
            print("Skipping record due to missing last name")
            continue
        if email == None or email == "":
            record['email'] = f"{first_name.lower()}.{last_name.lower()}@gmail.com"
        if phone_number == None:
            record['phone_number'] = "0700000000"
        else:
            record['phone_number'] = str(phone_number)
        if area_of_residence == None:
            record['area_of_residence'] = ""
        if is_producer == None:
            record['is_producer'] = False
        if is_assistant_producer == None:
            record['is_assistant_producer'] = False
        if is_active == None:
            record['is_active'] = True
        if roles:
            role_objs = []
            roles = parse_roles(roles)
            print(f"Parsed roles: {roles}")
            for role_name in roles:
                print(f"Processing role: {role_name}")
                try:
                    role_obj = Roles.objects.get(name__iexact = role_name)
                    role_id = role_obj.id
                except:
                    role_obj = Roles.objects.create(name=role_name)
                    role_id = role_obj.id
                role_objs.append(role_id)
                role_name = role_objs
        else:
            role_name = None
            
        record.pop("roles", None)  # Remove roles to avoid issues in serializer
        serializer = PersonsSerializer(data=record)
        if serializer.is_valid():
            serializer.save()
            assortment_bulk_upload.success_products += 1
    return Response({
        "message": "Bulk upload completed",
        "total_records": number_of_records,
        "successful_uploads": assortment_bulk_upload.success_products
    }, status=201)


@api_view(['POST','GET'])
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
@api_view(['PUT', 'DELETE'])
def modify_role(request,id):
    if request.method == 'PUT':
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

@api_view(['POST','GET'])
def events(request):
    if request.method == 'POST':
        event_name = request.data.get('name')
        if event_name == None or event_name == "":
            return Response({"error": "Event name is required"}, status=400)
        if Events.objects.filter(name__iexact=event_name).exists():
            return Response({"error": "Event with this name already exists"}, status=400)
        serializer = EventsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        events = Events.objects.all()
        serializer = EventsSerializer(events, many=True)
        return Response(serializer.data, status=200)
@api_view(['PUT', 'DELETE'])
def modify_event(request,id):
    if request.method == 'PUT':
        try:
            event = Events.objects.get(id=id)
        except Events.DoesNotExist:
            return Response({"error": "Event not found"}, status=404)
        event_name = request.data.get('name')
        if event_name == None or event_name == "":
            return Response({"error": "Event name is required"}, status=400)
        if 'name' in request.data:
            event_name = request.data.get('name')
            if Events.objects.filter(name__iexact=event_name).exclude(id=id).exists():
                return Response({"error": "Event with this name already exists"}, status=400)
        
        serializer = EventsSerializer(event, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        event_id = request.data.get('id')
        try:
            event = Events.objects.get(id=event_id)
            event.delete()
            return Response({"message": "Event deleted successfully"}, status=204)
        except Events.DoesNotExist:
            return Response({"error": "Event not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
@api_view(['GET'])
def event_detail(request, pk):
    try:
        event = Events.objects.get(pk=pk)
    except Events.DoesNotExist:
        return Response({"error": "Event not found"}, status=404)
    serializer = EventsSerializer(event)
    return Response(serializer.data, status=200)

@api_view(['POST', 'GET', 'PUT', 'DELETE'])
def rosters(request):
    if request.method == 'POST':
        date = request.data.get('date')
        if not date:
            return Response({'date': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            return Response({'date': ['Invalid date format. Use YYYY-MM-DD.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            structured_roster = generate_roster(date)
            return Response(structured_roster, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'GET':
        rosters = Rosters.objects.all()
        serializer = RostersSerializer(rosters, many=True)
        return Response(serializer.data)

    elif request.method == 'PUT':
        roster_id = request.data.get('id')
        try:
            roster = Rosters.objects.get(id=roster_id)
        except Rosters.DoesNotExist:
            return Response({"error": "Roster not found"}, status=404)

        serializer = RostersSerializer(roster, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        roster_id = request.data.get('id')
        try:
            roster = Rosters.objects.get(id=roster_id)
            roster.delete()
            return Response({"message": "Roster deleted successfully"}, status=204)
        except Rosters.DoesNotExist:
            return Response({"error": "Roster not found"}, status=404)

    return Response({"error": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['GET'])
def get_status(request):
    # returns the status choices for boolean field
    choices = [
        {'id': True, 'name': 'Available'},
        {'id': False, 'name': 'Unavailable'}
    ]
    return Response(choices, status=200)


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

# Legacy endpoints for backward compatibility

# Legacy endpoints for backward compatibility
@api_view(['POST'])
def save_roster(request):
    """Legacy save roster endpoint"""
    pass

@api_view(['POST'])
def generate_structured_roster(request):
    """Legacy generate roster endpoint"""
    pass

@api_view(['POST'])
def generate_and_download_roster(request):
    """Legacy PDF download endpoint"""
    pass

