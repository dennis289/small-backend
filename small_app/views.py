import ast
import json
import secrets
from datetime import datetime, date

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from scheduling.generator import RosterGenerator
from scheduling.services import generate_roster

from .models import (
    User, Persons, Roles, Events, Rosters, Assignment, MembersBulkUpload,
    AwardType, Award, RosterFeedback, MemberStreak, FeedbackShareLink,
)
from .pdf import export_roster_pdf
from .serializers import (
    UserSerializer, PersonsSerializer, RolesSerializer, EventsSerializer,
    RostersSerializer, AssignmentSerializer, AwardTypeSerializer,
    AwardSerializer, RosterFeedbackSerializer,
)


class MyPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 70


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

def _user_payload(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
    }

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    user = request.user
    if request.method == 'GET':
        serializer = UserSerializer(user)
        return Response(serializer.data, status=200)

    data = request.data
    for field in ['username', 'email', 'first_name', 'last_name']:
        if field in data and data[field] != '':
            setattr(user, field, data[field])

    if data.get('new_password'):
        if not user.check_password(data.get('current_password', '')):
            return Response({'error': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(data['new_password'])

    user.save()
    return Response({**_user_payload(user), 'message': 'Profile updated successfully'})

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
        search_term = request.query_params.get('search', '').strip()
        persons = Persons.objects.all()
        if search_term:
            persons = persons.filter(
                Q(first_name__icontains=search_term) |
                Q(last_name__icontains=search_term) |
                Q(email__icontains=search_term)
            )
        paginator = MyPagination()
        paginated_persons = paginator.paginate_queryset(persons, request)
        serializer = PersonsSerializer(paginated_persons, many=True)
        return paginator.get_paginated_response(serializer.data)

@api_view(['GET'])
def active_members(request):
    active_persons = Persons.objects.filter(is_active=True)
    serializer = PersonsSerializer(active_persons, many=True)
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
        role_ids = []
        if roles:
            roles = parse_roles(roles)
            for rname in roles:
                role_obj, _ = Roles.objects.get_or_create(name__iexact=rname, defaults={'name': rname})
                role_ids.append(role_obj.id)

        record.pop("roles", None)  # Remove roles to avoid issues in serializer
        serializer = PersonsSerializer(data=record)
        if serializer.is_valid():
            person = serializer.save()
            if role_ids:
                person.roles.set(role_ids)
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
        
        absent_members = request.data.get('absent_members', [])
        inactive_events = request.data.get('inactive_events', [])
        if absent_members:
            Persons.objects.filter(id__in=absent_members).update(is_present=False)
        if inactive_events:
            Events.objects.filter(id__in=inactive_events).update(is_active=False)


        try:
            structured_roster = generate_roster(date)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Absence is per-generation: restore flags so the next roster starts clean.
        # if absent_members:
        #     Persons.objects.filter(id__in=absent_members).update(is_present=True)
        # if inactive_events:
        #     Events.objects.filter(id__in=inactive_events).update(is_active=True)

        return Response(structured_roster, status=status.HTTP_201_CREATED)

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
# Award CRUD  (decoupled from events)
# ──────────────────────────────────────────
def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@api_view(['GET', 'POST'])
def awards(request):
    if request.method == 'GET':
        qs = Award.objects.select_related('person', 'award_type', 'given_by').all()

        person_id = request.query_params.get('person')
        type_id = request.query_params.get('type')
        from_str = request.query_params.get('from')
        to_str = request.query_params.get('to')

        if person_id:
            qs = qs.filter(person_id=person_id)
        if type_id:
            qs = qs.filter(award_type_id=type_id)
        from_date = _parse_date(from_str)
        to_date = _parse_date(to_str)
        if from_date:
            qs = qs.filter(given_at__gte=from_date)
        if to_date:
            qs = qs.filter(given_at__lte=to_date)

        paginator = MyPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AwardSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    # POST
    serializer = AwardSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    person = serializer.validated_data['person']

    # Snapshot the streak *before* it resets, so the award shows the streak it earned.
    streak, _ = MemberStreak.objects.get_or_create(person=person)
    streak_snapshot = streak.current_streak

    given_by = request.user if request.user.is_authenticated else None
    if not serializer.validated_data.get('given_at'):
        serializer.validated_data['given_at'] = date.today()

    award = serializer.save(streak_at_award=streak_snapshot, given_by=given_by)

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak
    streak.current_streak = 0
    streak.save()

    return Response(AwardSerializer(award).data, status=201)


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
def award_stats(request):
    """Aggregate counts for the awards dashboard."""
    from django.db.models import Count
    from django.db.models.functions import TruncMonth

    today = date.today()
    month_start = today.replace(day=1)
    qs = Award.objects.all()

    by_type = list(
        qs.values('award_type', 'award_type__name')
          .annotate(count=Count('id'))
          .order_by('-count')
    )
    by_type = [
        {'award_type_id': row['award_type'], 'name': row['award_type__name'], 'count': row['count']}
        for row in by_type
    ]

    top_recipients = list(
        qs.values('person', 'person__first_name', 'person__last_name')
          .annotate(count=Count('id'))
          .order_by('-count')[:10]
    )
    top_recipients = [
        {
            'person_id': row['person'],
            'name': f"{row['person__first_name']} {row['person__last_name']}".strip(),
            'count': row['count'],
        }
        for row in top_recipients
    ]

    by_month = list(
        qs.annotate(month=TruncMonth('given_at'))
          .values('month')
          .annotate(count=Count('id'))
          .order_by('month')
    )
    by_month = [
        {'month': row['month'].strftime('%Y-%m'), 'count': row['count']}
        for row in by_month if row['month']
    ]

    return Response({
        'total': qs.count(),
        'this_month': qs.filter(given_at__gte=month_start).count(),
        'unique_recipients': qs.values('person').distinct().count(),
        'unique_types': qs.values('award_type').distinct().count(),
        'by_type': by_type,
        'top_recipients': top_recipients,
        'by_month': by_month,
    }, status=200)


@api_view(['GET'])
def person_awards(request, pk):
    """Return all awards received by a single person."""
    if not Persons.objects.filter(pk=pk).exists():
        return Response({"error": "Person not found"}, status=404)
    qs = (
        Award.objects
        .filter(person_id=pk)
        .select_related('award_type', 'given_by')
    )
    return Response(AwardSerializer(qs, many=True).data, status=200)


# ──────────────────────────────────────────
# Roster Feedback
# ──────────────────────────────────────────
def _recalculate_streak(person_id):
    """Recompute and persist the attendance streak for a single person."""
    try:
        person = Persons.objects.get(pk=person_id)
    except Persons.DoesNotExist:
        return

    feedbacks = (
        RosterFeedback.objects
        .filter(person=person)
        .select_related('roster')
        .order_by('-roster__date')
    )

    current_streak = 0
    for fb in feedbacks:
        if fb.is_present:
            current_streak += 1
        else:
            break

    streak, _ = MemberStreak.objects.get_or_create(person=person)
    if current_streak > streak.longest_streak:
        streak.longest_streak = current_streak
    streak.current_streak = current_streak
    streak.save()


@api_view(['GET'])
def person_streaks(request):
    """Return current and longest attendance streak for every active member."""
    persons = Persons.objects.filter(is_active=True).select_related('streak')
    result = []
    for person in persons:
        streak = getattr(person, 'streak', None)
        result.append({
            'person_id': person.pk,
            'name': f"{person.first_name} {person.last_name}".strip(),
            'current_streak': streak.current_streak if streak else 0,
            'longest_streak': streak.longest_streak if streak else 0,
        })
    result.sort(key=lambda x: x['current_streak'], reverse=True)
    return Response(result, status=200)


@api_view(['GET'])
def roster_persons(request, roster_id):
    """Return all persons assigned to a roster with their current feedback status."""
    try:
        roster = Rosters.objects.get(pk=roster_id)
    except Rosters.DoesNotExist:
        return Response({"error": "Roster not found"}, status=404)

    assignments = Assignment.objects.filter(roster=roster).select_related('person', 'role')

    feedback_map = {
        f.person_id: f
        for f in RosterFeedback.objects.filter(roster=roster)
    }

    seen = set()
    result = []
    for a in assignments:
        p = a.person
        if p.pk in seen:
            continue
        seen.add(p.pk)
        fb = feedback_map.get(p.pk)
        result.append({
            'person_id': p.pk,
            'first_name': p.first_name,
            'last_name': p.last_name,
            'role': a.role.name,
            'is_present': fb.is_present if fb else True,
            'feedback': fb.feedback if fb else '',
        })

    return Response(result, status=200)




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
    person_ids = []
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
                'rating': item.get('rating') or None,
                'feedback_category': item.get('feedback_category') or None,
            }
        )
        person_ids.append(person_id)
        if was_created:
            created += 1
        else:
            updated += 1

    for pid in person_ids:
        _recalculate_streak(pid)

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


# ──────────────────────────────────────────
# Shareable feedback link (public, one-time use)
# ──────────────────────────────────────────
def _build_share_payload(link):
    """Aggregate every roster + assignment for the link's date into a single payload."""
    rosters_qs = (
        Rosters.objects
        .filter(date=link.date)
        .select_related('event')
        .prefetch_related('assignments__person', 'assignments__role')
        .order_by('event__id')
    )

    events_payload = []
    seen_person_ids = set()
    members_payload = []

    for roster in rosters_qs:
        assignments = []
        for a in roster.assignments.all().order_by('role__name'):
            assignments.append({
                'person_id': a.person.pk,
                'name': f"{a.person.first_name} {a.person.last_name}".strip(),
                'role': a.role.name,
            })
            if a.person.pk not in seen_person_ids:
                seen_person_ids.add(a.person.pk)
                members_payload.append({
                    'person_id': a.person.pk,
                    'name': f"{a.person.first_name} {a.person.last_name}".strip(),
                })
        events_payload.append({
            'roster_id': roster.pk,
            'event_id': roster.event.pk if roster.event else None,
            'event_name': roster.event.name if roster.event else 'Unnamed event',
            'assignments': assignments,
        })

    members_payload.sort(key=lambda m: m['name'])

    return {
        'date': str(link.date),
        'is_used': link.is_used,
        'events': events_payload,
        'members': members_payload,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_feedback_share_link(request):
    """Create a one-time share link for a roster date. Authenticated admin endpoint.

    Body: { "date": "YYYY-MM-DD" }
    Returns: { token, date, share_url }
    """
    date_str = request.data.get('date')
    if not date_str:
        return Response({'error': 'date is required (YYYY-MM-DD)'}, status=400)
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'error': 'Invalid date format'}, status=400)

    if not Rosters.objects.filter(date=target_date).exists():
        return Response(
            {'error': f'No saved roster for {date_str}. Save the roster before generating a share link.'},
            status=400,
        )

    # Once feedback has been collected for a date, don't allow another link —
    # the day's attendance is final.
    if RosterFeedback.objects.filter(roster__date=target_date).exists():
        return Response(
            {'error': f'Feedback has already been collected for {date_str}.'},
            status=409,
        )

    token = secrets.token_urlsafe(32)
    link = FeedbackShareLink.objects.create(
        token=token,
        date=target_date,
        created_by=request.user if request.user.is_authenticated else None,
    )

    # Build an absolute, reachable URL when FRONTEND_BASE_URL is configured.
    # Otherwise return None and let the frontend fall back to its own origin.
    from django.conf import settings
    share_url = (
        f"{settings.FRONTEND_BASE_URL}/feedback/share/{link.token}"
        if settings.FRONTEND_BASE_URL else None
    )

    return Response({
        'token': link.token,
        'date': str(link.date),
        'created_at': link.created_at.isoformat(),
        'share_url': share_url,
    }, status=201)


@api_view(['GET'])
def feedback_share_get(request, token):
    """Public: fetch the form data for a share link."""
    try:
        link = FeedbackShareLink.objects.get(token=token)
    except FeedbackShareLink.DoesNotExist:
        return Response({'error': 'Link not found'}, status=404)
    if link.is_used:
        return Response({'error': 'This link has already been used.'}, status=410)
    return Response(_build_share_payload(link), status=200)


@api_view(['POST'])
def feedback_share_submit(request, token):
    """Public: submit feedback through a one-time share link.

    Body:
      {
        "attendance": [{"person_id": 1, "is_present": true}, ...],
        "global_feedback": "Overall notes..."
      }

    Creates a RosterFeedback row per (roster, person) for every roster on the
    link's date, using the same is_present value for that person across all
    rosters they're assigned to. Marks the link as used so it can't be replayed.
    """
    try:
        link = FeedbackShareLink.objects.get(token=token)
    except FeedbackShareLink.DoesNotExist:
        return Response({'error': 'Link not found'}, status=404)
    if link.is_used:
        return Response({'error': 'This link has already been used.'}, status=410)

    attendance = request.data.get('attendance', [])
    global_feedback = request.data.get('global_feedback', '') or ''

    presence_by_person = {}
    for item in attendance:
        pid = item.get('person_id')
        if pid is None:
            continue
        presence_by_person[int(pid)] = bool(item.get('is_present', True))

    rosters_for_day = list(Rosters.objects.filter(date=link.date))
    if not rosters_for_day:
        return Response({'error': 'No rosters exist for that date anymore.'}, status=400)

    affected_person_ids = set()
    with transaction.atomic():
        # Atomically claim the link: only one request can flip is_used False->True.
        # If a concurrent submit already claimed it, claimed == 0 and we bail out,
        # so the feedback writes below never run twice.
        claimed = FeedbackShareLink.objects.filter(
            pk=link.pk, is_used=False
        ).update(
            is_used=True,
            used_at=timezone.now(),
            global_feedback=global_feedback,
        )
        if not claimed:
            return Response({'error': 'This link has already been used.'}, status=410)

        for roster in rosters_for_day:
            assigned_person_ids = set(
                Assignment.objects.filter(roster=roster).values_list('person_id', flat=True)
            )
            for person_id in assigned_person_ids:
                is_present = presence_by_person.get(person_id, True)
                RosterFeedback.objects.update_or_create(
                    roster=roster,
                    person_id=person_id,
                    defaults={
                        'is_present': is_present,
                        'feedback': global_feedback,
                    },
                )
                affected_person_ids.add(person_id)

    for pid in affected_person_ids:
        _recalculate_streak(pid)

    return Response({
        'message': 'Feedback submitted. Thank you.',
        'date': str(link.date),
        'affected_members': len(affected_person_ids),
    }, status=200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def feedback_summary(request):
    """Per-date summary of collected feedback: who was present and the day's note.

    Used by the admin feedback page to list already-collected days and to know
    which dates should no longer offer link generation.
    """
    feedbacks = (
        RosterFeedback.objects
        .select_related('person', 'roster')
        .order_by('-roster__date')
    )

    # Day-level note preferred from the share link used for that date.
    link_notes = {
        str(link.date): link.global_feedback
        for link in FeedbackShareLink.objects.filter(is_used=True)
        if link.global_feedback
    }

    by_date = {}
    for fb in feedbacks:
        key = str(fb.roster.date)
        entry = by_date.get(key)
        if entry is None:
            entry = {
                'date': key,
                'present': {},
                'absent': {},
                'notes': set(),
                'submitted_at': fb.updated_at,
            }
            by_date[key] = entry
        name = f"{fb.person.first_name} {fb.person.last_name}".strip()
        if fb.is_present:
            entry['present'][fb.person_id] = name
            entry['absent'].pop(fb.person_id, None)
        elif fb.person_id not in entry['present']:
            entry['absent'][fb.person_id] = name
        if fb.feedback:
            entry['notes'].add(fb.feedback)
        if fb.updated_at > entry['submitted_at']:
            entry['submitted_at'] = fb.updated_at

    result = []
    for key, entry in by_date.items():
        day_note = link_notes.get(key) or ' / '.join(sorted(entry['notes']))
        result.append({
            'date': entry['date'],
            'present': sorted(entry['present'].values()),
            'absent': sorted(entry['absent'].values()),
            'present_count': len(entry['present']),
            'absent_count': len(entry['absent']),
            'feedback': day_note,
            'submitted_at': entry['submitted_at'].isoformat(),
        })
    result.sort(key=lambda x: x['date'], reverse=True)
    return Response(result, status=200)

