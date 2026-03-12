import ast
import json
from django.shortcuts import render
from .serializers import (
    UserSerializer, LoginSerializer, PersonsSerializer,
    RolesSerializer, EventsSerializer, RostersSerializer, AssignmentSerializer,
    AwardTypeSerializer, AwardSerializer, RosterFeedbackSerializer,
)
from .models import (
    User, Persons, Roles, Events, Rosters, Assignment, MembersBulkUpload,
    AwardType, Award, RosterFeedback,
)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .scheduler import generate_roster
from datetime import datetime, date, time
from .pdf import export_roster_pdf
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
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)
    
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
        mobile_number = request.data.get('phone_number')
        number = Persons.objects.filter(phone_number=mobile_number).exists()
        if number:
            return Response({"error": "Person with this phone number already exists"}, status=400)
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
def modify_person(request, id):
    try:
        person = Persons.objects.get(id=id)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)

    if request.method == 'PUT':
        serializer = PersonsSerializer(person, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        person.delete()
        return Response({"message": "Person deleted successfully"}, status=204)
@api_view(['GET'])
def person_detail(request, pk):
    try:
        person = Persons.objects.get(pk=pk)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)
    serializer = PersonsSerializer(person)
    return Response(serializer.data, status=200)

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

        if not first_name:
            print("Skipping record due to missing first name")
            continue
        if not last_name:
            print("Skipping record due to missing last name")
            continue
        if not email:
            record['email'] = f"{first_name.lower()}.{last_name.lower()}@gmail.com"
        if not phone_number:
            record['phone_number'] = "0700000000"
        else:
            record['phone_number'] = str(phone_number)
        if not area_of_residence:
            record['area_of_residence'] = ""
        if not is_producer:
            record['is_producer'] = False
        if not is_assistant_producer:
            record['is_assistant_producer'] = False
        if not is_active:
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
def modify_role(request, id):
    try:
        role = Roles.objects.get(id=id)
    except Roles.DoesNotExist:
        return Response({"error": "Role not found"}, status=404)

    if request.method == 'PUT':
        serializer = RolesSerializer(role, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        role.delete()
        return Response({"message": "Role deleted successfully"}, status=204)
    
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
        if not event_name:
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
def modify_event(request, id):
    try:
        event = Events.objects.get(id=id)
    except Events.DoesNotExist:
        return Response({"error": "Event not found"}, status=404)

    if request.method == 'PUT':
        event_name = request.data.get('name')
        if not event_name:
            return Response({"error": "Event name is required"}, status=400)
        if Events.objects.filter(name__iexact=event_name).exclude(id=id).exists():
            return Response({"error": "Event with this name already exists"}, status=400)
        serializer = EventsSerializer(event, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        event.delete()
        return Response({"message": "Event deleted successfully"}, status=204)
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
@api_view(['POST'])
def save_roster(request):
    """Save an edited roster back to the database."""
    roster_data = request.data.get('data')
    date_str = request.data.get('date')

    if not roster_data or not date_str:
        return Response(
            {"error": "Both 'data' and 'date' fields are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {"error": "Invalid date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        from .scheduler import RosterGenerator
        generator = RosterGenerator()
        generator.save_roster_to_database(roster_data, target_date)
        return Response({"message": "Roster saved successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def generate_and_download_roster(request):
    """Return a PDF of the supplied roster data."""
    roster_data = request.data.get('roster_data')
    if not roster_data:
        return Response(
            {"error": "'roster_data' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        pdf_bytes = export_roster_pdf(roster_data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    date_str = roster_data.get('date', 'roster')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="roster_{date_str}.pdf"'
    return response


# ──────────────────────────────────────────
# Award-type CRUD
# ──────────────────────────────────────────
@api_view(['GET', 'POST'])
def award_types(request):
    if request.method == 'GET':
        qs = AwardType.objects.all()
        serializer = AwardTypeSerializer(qs, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'POST':
        serializer = AwardTypeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
def award_type_detail(request, pk):
    try:
        award_type = AwardType.objects.get(pk=pk)
    except AwardType.DoesNotExist:
        return Response({"error": "Award type not found"}, status=404)

    if request.method == 'GET':
        serializer = AwardTypeSerializer(award_type)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        serializer = AwardTypeSerializer(award_type, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        award_type.delete()
        return Response({"message": "Award type deleted"}, status=204)


# ──────────────────────────────────────────
# Award CRUD  (one per event)
# ──────────────────────────────────────────
@api_view(['GET', 'POST'])
def awards(request):
    if request.method == 'GET':
        qs = Award.objects.select_related('event', 'person', 'award_type').all()
        serializer = AwardSerializer(qs, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'POST':
        serializer = AwardSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
def award_detail(request, pk):
    try:
        award = Award.objects.get(pk=pk)
    except Award.DoesNotExist:
        return Response({"error": "Award not found"}, status=404)

    if request.method == 'GET':
        serializer = AwardSerializer(award)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        serializer = AwardSerializer(award, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        award.delete()
        return Response({"message": "Award deleted"}, status=204)


@api_view(['GET'])
def event_award(request, event_id):
    """Return the award for a specific event, or null if none."""
    try:
        award = Award.objects.select_related('event', 'person', 'award_type').get(event_id=event_id)
        return Response(AwardSerializer(award).data, status=200)
    except Award.DoesNotExist:
        return Response(None, status=200)


# ──────────────────────────────────────────
# Roster Feedback
# ──────────────────────────────────────────
@api_view(['GET'])
def roster_persons(request, roster_id):
    """Return all active persons with any existing feedback for the given roster."""
    try:
        roster = Rosters.objects.get(pk=roster_id)
    except Rosters.DoesNotExist:
        return Response({"error": "Roster not found"}, status=404)

    persons = Persons.objects.filter(is_active=True).order_by('first_name', 'last_name')
    existing = {
        fb.person_id: fb
        for fb in RosterFeedback.objects.filter(roster=roster)
    }

    data = []
    for p in persons:
        fb = existing.get(p.id)
        data.append({
            'person_id': p.id,
            'person_name': f"{p.first_name} {p.last_name}".strip(),
            'is_present': fb.is_present if fb else False,
            'feedback': fb.feedback if fb else '',
            'feedback_id': fb.id if fb else None,
        })
    return Response(data, status=200)


@api_view(['POST'])
def submit_feedback(request, roster_id):
    """Bulk create/update feedback for a roster.
    Expects: { "feedback": [ { "person_id": 1, "is_present": true, "feedback": "..." }, ... ] }
    """
    try:
        roster = Rosters.objects.get(pk=roster_id)
    except Rosters.DoesNotExist:
        return Response({"error": "Roster not found"}, status=404)

    items = request.data.get('feedback', [])
    if not items:
        return Response({"error": "No feedback data provided"}, status=400)

    created = 0
    updated = 0
    for item in items:
        person_id = item.get('person_id')
        if not person_id:
            continue
        obj, was_created = RosterFeedback.objects.update_or_create(
            roster=roster,
            person_id=person_id,
            defaults={
                'is_present': item.get('is_present', False),
                'feedback': item.get('feedback', ''),
            }
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return Response({
        "message": "Feedback saved successfully",
        "created": created,
        "updated": updated,
    }, status=200)


@api_view(['GET'])
def roster_feedback(request, roster_id):
    """Return all feedback entries for a roster."""
    qs = RosterFeedback.objects.filter(
        roster_id=roster_id
    ).select_related('person', 'roster__event')
    serializer = RosterFeedbackSerializer(qs, many=True)
    return Response(serializer.data, status=200)

