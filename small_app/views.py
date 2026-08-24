"""REST endpoints for the roster app, mounted under ``/api/``.

All views are function-based DRF views. ``REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES``
is ``IsAuthenticated``, so every endpoint here requires a JWT unless it explicitly
opts out with ``@permission_classes([AllowAny])`` (only the login and public
feedback-share endpoints do).

There are two orthogonal access checks, and both matter:

**Which client's data** — enforced by hand rather than by middleware:
  * reads go through ``scoped(Model, request)``;
  * writes stamp ``client=current_client(request)``;
  * FK inputs are validated by ``ClientScopedPrimaryKeyRelatedField`` in serializers,
    so a client can't reference another client's rows by guessing IDs.

**What this user may do with it** — enforced by the permission class on each view
(see ``permissions.py``). Roughly:

  ================================  ==========================================
  ``IsClientAdminOrSchedulerReadOnly``  setup data: admins write, schedulers read
  ``CanSchedule``                   rostering and attendance: admin + scheduler
  ``IsClientAdmin``                 awards, user management, destructive actions
  ``IsTenantUser``                  published rosters — every role, read-only
  ``IsPlatformAdmin``               tenant management (``admin_*`` views)
  ================================  ==========================================

Every tenant endpoint must carry one of these explicitly. Falling back to the
project default would let a member call it.

Platform superadmins have ``client=None``, which makes ``scoped()`` return an empty
queryset and every tenant permission class refuse them — they use the ``admin_*``
views at the bottom of this module instead.
"""

import ast
import json
import secrets
from datetime import datetime, date

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from scheduling.generator import RosterGenerator
from scheduling.services import generate_roster, get_assignment_statistics

from .models import (
    User, Client, Persons, Roles, Events, Rosters, Assignment, MembersBulkUpload,
    AwardType, Award, RosterFeedback, MemberStreak, FeedbackShareLink,
)


def current_client(request):
    """The requesting user's client (None for platform/superadmin accounts)."""
    return getattr(request.user, 'client', None)


def scoped(model, request):
    """A queryset of ``model`` limited to the requesting user's client.

    Every tenant-facing endpoint reads through this so data never crosses
    client boundaries. Writes must stamp ``client=current_client(request)``.
    """
    return model.objects.filter(client=current_client(request))
from django.utils.text import slugify

from .pdf import export_roster_pdf
from .permissions import (
    CanSchedule, IsClientAdmin, IsClientAdminOrSchedulerReadOnly,
    IsPlatformAdmin, IsTenantUser,
)
from .serializers import (
    UserSerializer, ClientSerializer, PersonsSerializer, RolesSerializer,
    EventsSerializer, RostersSerializer, AssignmentSerializer, AwardTypeSerializer,
    AwardSerializer, RosterFeedbackSerializer,
)


class MyPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 70


def parse_roles(roles):
    """Coerce the many shapes a CSV import puts in the ``roles`` column into a list.

    Accepts a real list, a Python-literal string (``"['Camera', 'Sound']"``), a JSON
    array, or a plain comma-separated string, trying each in turn. Anything else is
    wrapped in a single-element list. Returns ``[]`` for empty input.
    """
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

# Public self-service sign-up is disabled in the multi-tenant setup: accounts
# are provisioned by a platform admin (Clients console) or a client admin, so a
# new user is always attached to the right client.
@api_view(['POST'])
@permission_classes([AllowAny])
def signup(request):
    return Response(
        {'error': 'Public sign-up is disabled. Ask your administrator for an account.'},
        status=403,
    )
    
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """Exchange email + password for a JWT pair.

    Body: ``{"email": "...", "password": "..."}``

    The email is used to look up the account, then Django authenticates against the
    *username* it resolves to. The response carries the user's client, their tenant
    ``role`` and their ``is_platform_admin`` flag; the frontend persists all three so
    the router guard can pick a landing page and gate routes without another call.
    """
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
            "client": (
                {'id': user.client.id, 'name': user.client.name, 'slug': user.client.slug}
                if user.client_id else None
            ),
            "is_platform_admin": user.client_id is None and user.is_superuser,
            # Tenant role — the frontend uses it to pick a landing page and hide
            # what this user can't do. Null for platform admins, who have no role.
            "role": user.role if user.client_id else None,
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
def get_tokens_for_user(user):
    """Mint a fresh refresh/access token pair for ``user``."""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

# --- Password reset -------------------------------------------------------
# Two steps, both public. Step one proves nothing and reveals nothing: it always
# answers the same way, so the endpoint can't be used to discover which emails
# have accounts. Ownership is proved in step two by possession of a token that
# was only ever sent to the address on file.
#
# The token is Django's ``default_token_generator``: signed with SECRET_KEY,
# expiring after PASSWORD_RESET_TIMEOUT, and single-use because the hash it
# signs includes the user's current password hash — changing the password
# invalidates every outstanding token for that account.

# Same answer whether or not the identifier matched, so the response can't be
# used to enumerate accounts.
_RESET_SENT_MESSAGE = (
    'If an account matches that username or email, a reset link has been sent to '
    'the email address on file.'
)


def _send_password_reset(user, request):
    """Email ``user`` a reset link pointing at the frontend."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    # FRONTEND_BASE_URL when configured, else the Origin the request came from,
    # so a LAN demo or a dev server both produce a link that actually resolves.
    base = settings.FRONTEND_BASE_URL or request.headers.get('Origin', '').rstrip('/')
    link = f"{base}/reset-password?uid={uid}&token={token}"

    send_mail(
        subject='Reset your password',
        message=(
            f"Hi {user.first_name or user.username},\n\n"
            f"Someone asked to reset the password for your account ({user.username}).\n"
            f"Open this link to choose a new one:\n\n{link}\n\n"
            f"The link expires in {settings.PASSWORD_RESET_TIMEOUT // 86400} days and "
            f"can only be used once. If you didn't ask for this, ignore this email — "
            f"your password stays as it is.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return link


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    """Start a password reset.

    Body: ``{"identifier": "..."}`` — either a username or an email address.

    Always returns 200 with the same message, whether or not anything matched.
    Accounts with no email on file, and deactivated accounts, are skipped
    silently for the same reason.
    """
    identifier = (request.data.get('identifier') or '').strip()
    if not identifier:
        return Response(
            {'error': 'Enter your username or email address.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.filter(
        Q(username__iexact=identifier) | Q(email__iexact=identifier),
        is_active=True,
    ).exclude(email='').first()

    if user:
        _send_password_reset(user, request)

    return Response({'detail': _RESET_SENT_MESSAGE}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """Finish a password reset.

    Body: ``{"uid": "...", "token": "...", "new_password": "..."}``

    The new password goes through Django's configured validators, so the rules
    here are the same ones applied anywhere else in the project.
    """
    uid = request.data.get('uid') or ''
    token = request.data.get('token') or ''
    new_password = request.data.get('new_password') or ''

    if not (uid and token and new_password):
        return Response(
            {'error': 'This reset link is incomplete. Open the link from your email again, or request a new one.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # A malformed uid is indistinguishable from a wrong one, on purpose.
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uid).decode())
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return Response(
            {'error': 'This reset link is invalid or has expired. Request a new one.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, user)
    except DjangoValidationError as exc:
        return Response({'error': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save(update_fields=['password'])

    # Changing the password rotates the token hash, so the link just used — and
    # any other outstanding one — stops working from here.
    return Response(
        {'detail': 'Password updated. You can now sign in with your new password.'},
        status=status.HTTP_200_OK,
    )


def _user_payload(user):
    """User dict returned after a profile update.

    Includes the identity fields the frontend caches and routes on — ``role`` and
    ``is_platform_admin`` — because the client stores this response as the current
    user. Leaving them out silently downgraded the cached user and locked admins
    out of their own console on the next navigation.
    """
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role if user.client_id else None,
        'is_platform_admin': user.is_platform_admin,
    }

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    """GET the logged-in user's profile, or PATCH name/username/email/password.

    On PATCH, blank values are ignored (so the frontend can send the whole form).
    Changing the password requires ``current_password`` to match.
    """
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
            return Response({'error': 'That is not your current password. Try again.'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(data['new_password'])

    user.save()
    return Response({**_user_payload(user), 'message': 'Profile updated successfully'})

@api_view(['POST','GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def persons(request):
    """List (paginated, searchable) or create team members for the current client.

    GET  ``?search=`` matches first name, last name or email; 25 per page by default.

    POST rejects a phone number or email already used by another person in this
    client. Email carries a unique-per-client constraint, so without the check
    here a repeat address reaches the database and comes back as an IntegrityError
    — a 500 the caller can do nothing with. Re-adding somebody who is already on
    the team is the most ordinary mistake there is, and it deserves a sentence
    rather than a server error.
    """
    if request.method == 'POST':
        mobile_number = (request.data.get('phone_number') or '').strip()
        # Only a phone that was actually supplied can clash. Matching on a blank
        # one used to collide with every member who has no number on file.
        if mobile_number and scoped(Persons, request).filter(phone_number=mobile_number).exists():
            return Response(
                {"error": "Someone on your team already has that phone number."},
                status=400,
            )
        email_address = (request.data.get('email') or '').strip()
        if email_address and scoped(Persons, request).filter(email__iexact=email_address).exists():
            return Response(
                {"error": "Someone on your team already has that email address."},
                status=400,
            )
        serializer = PersonsSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(client=current_client(request))
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        search_term = request.query_params.get('search', '').strip()
        # Explicit ordering: without it the paginator can repeat or drop rows
        # between pages, since the database is free to return them in any order.
        persons = scoped(Persons, request).order_by('first_name', 'last_name', 'id')
        if search_term:
            persons = persons.filter(
                Q(first_name__icontains=search_term) |
                Q(last_name__icontains=search_term) |
                Q(email__icontains=search_term)
            )
        paginator = MyPagination()
        paginated_persons = paginator.paginate_queryset(persons, request)
        serializer = PersonsSerializer(paginated_persons, many=True)
        response = paginator.get_paginated_response(serializer.data)

        # Whole-directory tallies for the summary tiles above the table. Counted
        # over the filtered queryset rather than the current page, so the numbers
        # describe the directory instead of whichever ten rows happen to be shown.
        response.data['counts'] = persons.aggregate(
            total=Count('id'),
            producers=Count('id', filter=Q(is_producer=True, is_active=True)),
            assistants=Count('id', filter=Q(is_assistant_producer=True, is_active=True)),
            inactive=Count('id', filter=Q(is_active=False)),
        )
        return response

@api_view(['GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def active_members(request):
    """Unpaginated list of active members — feeds the roster editor's pickers."""
    active_persons = scoped(Persons, request).filter(is_active=True)
    serializer = PersonsSerializer(active_persons, many=True)
    return Response(serializer.data, status=200)

@api_view(['PUT', 'DELETE'])
@permission_classes([IsClientAdmin])
def modify_person(request, id):
    """Partially update (PUT) or hard-delete (DELETE) a member.

    DELETE cascades to that person's assignments, feedback, streak and awards.
    Deactivating via ``is_active=False`` is usually what you want instead.
    """
    try:
        person = scoped(Persons, request).get(id=id)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)

    if request.method == 'PUT':
        email_address = (request.data.get('email') or '').strip()
        if email_address and (
            scoped(Persons, request)
            .filter(email__iexact=email_address)
            .exclude(pk=person.pk)
            .exists()
        ):
            return Response(
                {"error": "Someone else on your team already has that email address."},
                status=400,
            )
        serializer = PersonsSerializer(person, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        person.delete()
        return Response({"message": "Person deleted successfully"}, status=204)
@api_view(['GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def person_detail(request, pk):
    """Fetch one member of the current client."""
    try:
        person = scoped(Persons, request).get(pk=pk)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)
    serializer = PersonsSerializer(person)
    return Response(serializer.data, status=200)

@api_view(['POST'])
@permission_classes([IsClientAdmin])
def bulk_upload_persons(request):
    """Import many members at once from a parsed CSV.

    Body: ``{"data": [ {first_name, last_name, email, contact, area_of_residence,
    roles, ...}, ... ]}`` — the frontend parses the CSV with PapaParse and posts rows.

    Records missing a first or last name are skipped; missing email/phone/area get
    placeholder defaults so the row still imports. Role names are matched
    case-insensitively and auto-created for this client if they don't exist yet.
    The whole payload is archived in ``MembersBulkUpload`` for auditing.
    """
    json_data = request.data.get('data')
    if not json_data:
        return Response({"error": "No data provided"}, status=400)
    number_of_records = len(json_data)
    client = current_client(request)
    assortment_bulk_upload = MembersBulkUpload.objects.create(
        json_data=json_data, number_of_records=number_of_records, client=client)
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
                role_obj, _ = scoped(Roles, request).get_or_create(
                    name__iexact=rname, defaults={'name': rname, 'client': client}
                )
                role_ids.append(role_obj.id)

        record.pop("roles", None)  # Remove roles to avoid issues in serializer
        serializer = PersonsSerializer(data=record, context={'request': request})
        if serializer.is_valid():
            person = serializer.save(client=client)
            if role_ids:
                person.roles.set(role_ids)
            assortment_bulk_upload.success_products += 1
    return Response({
        "message": "Bulk upload completed",
        "total_records": number_of_records,
        "successful_uploads": assortment_bulk_upload.success_products
    }, status=201)


@api_view(['POST','GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def roles(request):
    """List or create roles for the current client."""
    if request.method == 'POST':
        serializer = RolesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(client=current_client(request))
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        roles = scoped(Roles, request)
        serializer = RolesSerializer(roles, many=True)
        return Response(serializer.data, status=200)
@api_view(['POST'])
@permission_classes([IsClientAdmin])
def reorder_roles(request):
    """Rewrite the roles' display order in one shot.

    Body: ``{"order": [<role_id>, ...]}`` — the ids in the order the admin dragged
    them into. Ids are positioned by their index in that list, so the client sends
    what it shows and doesn't have to compute per-role numbers.

    Only roles belonging to the caller's client are touched; unknown ids are
    rejected rather than silently skipped, so a stale page can't half-apply an
    order. Roles left out of the list keep their current position.
    """
    order = request.data.get('order')
    if not isinstance(order, list):
        return Response(
            {'error': 'Send {"order": [role_id, ...]}.'}, status=400
        )

    roles_by_id = {r.pk: r for r in scoped(Roles, request).filter(pk__in=order)}
    missing = [rid for rid in order if rid not in roles_by_id]
    if missing:
        return Response(
            {'error': f'Unknown role ids: {missing}. Reload the page and try again.'},
            status=400,
        )

    to_update = []
    for position, role_id in enumerate(order):
        role = roles_by_id[role_id]
        role.display_order = position
        to_update.append(role)

    if to_update:
        Roles.objects.bulk_update(to_update, ['display_order'])

    return Response(
        RolesSerializer(scoped(Roles, request), many=True).data, status=200
    )


@api_view(['PUT', 'DELETE'])
@permission_classes([IsClientAdmin])
def modify_role(request, id):
    """Update or delete a role. Deleting one removes every assignment that used it."""
    try:
        role = scoped(Roles, request).get(id=id)
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
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def role_detail(request, pk):
    """Fetch one role of the current client."""
    try:
        role = scoped(Roles, request).get(pk=pk)
    except Roles.DoesNotExist:
        return Response({"error": "Role not found"}, status=404)

    serializer = RolesSerializer(role)
    return Response(serializer.data, status=200)

@api_view(['POST','GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def events(request):
    """List or create events. Names are unique per client, checked case-insensitively.

    The ``roles`` field on the payload binds which roles this event needs staffed —
    an event with no roles generates no assignments.
    """
    if request.method == 'POST':
        event_name = request.data.get('name')
        if not event_name:
            return Response({"error": "Event name is required"}, status=400)
        if scoped(Events, request).filter(name__iexact=event_name).exists():
            return Response({"error": "Event with this name already exists"}, status=400)
        serializer = EventsSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(client=current_client(request))
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        events = scoped(Events, request)
        serializer = EventsSerializer(events, many=True)
        return Response(serializer.data, status=200)
@api_view(['PUT', 'DELETE'])
@permission_classes([IsClientAdmin])
def modify_event(request, id):
    """Update or delete an event. Deleting removes its rosters and their assignments."""
    try:
        event = scoped(Events, request).get(id=id)
    except Events.DoesNotExist:
        return Response({"error": "Event not found"}, status=404)

    if request.method == 'PUT':
        event_name = request.data.get('name')
        if not event_name:
            return Response({"error": "Event name is required"}, status=400)
        if scoped(Events, request).filter(name__iexact=event_name).exclude(id=id).exists():
            return Response({"error": "Event with this name already exists"}, status=400)
        serializer = EventsSerializer(event, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        event.delete()
        return Response({"message": "Event deleted successfully"}, status=204)
@api_view(['GET'])
@permission_classes([IsClientAdminOrSchedulerReadOnly])
def event_detail(request, pk):
    """Fetch one event of the current client."""
    try:
        event = scoped(Events, request).get(pk=pk)
    except Events.DoesNotExist:
        return Response({"error": "Event not found"}, status=404)
    serializer = EventsSerializer(event)
    return Response(serializer.data, status=200)

@api_view(['POST', 'GET', 'PUT', 'DELETE'])
@permission_classes([CanSchedule])
def rosters(request):
    """Roster collection endpoint. The POST here *generates* rather than creates.

    POST   ``{date, absent_members[], inactive_events[]}`` → runs the generator and
           returns the proposed roster as JSON. **Nothing is written to the database** —
           the frontend reviews/edits it and then posts to ``/api/rosters/save/``.
    GET    every saved ``Rosters`` row for this client.
    PUT    update a saved roster by ``id`` in the body.
    DELETE remove a saved roster by ``id`` in the body (cascades to its assignments).
    """
    if request.method == 'POST':
        date = request.data.get('date')
        if not date:
            return Response({'date': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            date = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            return Response({'date': ['Invalid date format. Use YYYY-MM-DD.']}, status=status.HTTP_400_BAD_REQUEST)
        
        client = current_client(request)
        absent_members = request.data.get('absent_members', [])
        inactive_events = request.data.get('inactive_events', [])

        # Absence / inactivity is per-generation only — exclude these for this
        # roster without mutating the persisted is_present / is_active flags.
        try:
            structured_roster = generate_roster(
                date,
                client=client,
                inactive_events=inactive_events,
                absent_members=absent_members,
            )
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(structured_roster, status=status.HTTP_201_CREATED)

    elif request.method == 'GET':
        rosters = scoped(Rosters, request)
        serializer = RostersSerializer(rosters, many=True)
        return Response(serializer.data)

    elif request.method == 'PUT':
        roster_id = request.data.get('id')
        try:
            roster = scoped(Rosters, request).get(id=roster_id)
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
            roster = scoped(Rosters, request).get(id=roster_id)
            roster.delete()
            return Response({"message": "Roster deleted successfully"}, status=204)
        except Rosters.DoesNotExist:
            return Response({"error": "Roster not found"}, status=404)

    return Response({"error": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['GET'])
@permission_classes([CanSchedule])
def get_status(request):
    """Availability choices for dropdowns — a static mapping of the boolean flag."""
    # returns the status choices for boolean field
    choices = [
        {'id': True, 'name': 'Available'},
        {'id': False, 'name': 'Unavailable'}
    ]
    return Response(choices, status=200)


@api_view(['POST','GET','PUT','DELETE'])
@permission_classes([CanSchedule])
def assignments(request):
    """CRUD over individual (roster, role, person) assignments.

    Used for manual fix-ups outside the generate/save cycle. PUT and DELETE take the
    target ``id`` in the request body rather than the URL.
    """
    if request.method == 'POST':
        serializer = AssignmentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(client=current_client(request))
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        assignments = scoped(Assignment, request)
        serializer = AssignmentSerializer(assignments, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        assignment_id = request.data.get('id')
        try:
            assignment = scoped(Assignment, request).get(id=assignment_id)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found"}, status=404)

        serializer = AssignmentSerializer(assignment, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        assignment_id = request.data.get('id')
        try:
            assignment = scoped(Assignment, request).get(id=assignment_id)
            assignment.delete()
            return Response({"message": "Assignment deleted successfully"}, status=204)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
    
@api_view(['GET'])
@permission_classes([CanSchedule])
def assignment_detail(request, pk):
    """Fetch one assignment of the current client."""
    try:
        assignment = scoped(Assignment, request).get(pk=pk)
    except Assignment.DoesNotExist:
        return Response({"error": "Assignment not found"}, status=404)

    serializer = AssignmentSerializer(assignment)
    return Response(serializer.data, status=200)

# Legacy endpoints for backward compatibility
@api_view(['POST'])
@permission_classes([CanSchedule])
def save_roster(request):
    """Persist a generated (and possibly hand-edited) roster.

    Body: ``{"data": <roster payload from POST /api/rosters/>, "date": "YYYY-MM-DD"}``

    This is what actually creates ``Rosters`` and ``Assignment`` rows, and therefore
    what feeds the generator's rotation history on subsequent runs. Saving the same
    date again replaces that date's assignments rather than duplicating them.
    """
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
        generator = RosterGenerator(client=current_client(request))
        generator.save_roster_to_database(roster_data, target_date)
        return Response({"message": "Roster saved successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ──────────────────────────────────────────
# Published roster views — open to every role, read-only.
# This is all a member can see, so it must not leak anything beyond who is
# rostered for what on a given day.
# ──────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsTenantUser])
def roster_dates(request):
    """Dates that have a saved roster, most recent first.

    Feeds the date picker on the read-only schedule view.
    """
    dates = (
        scoped(Rosters, request)
        .values_list('date', flat=True)
        .distinct()
        .order_by('-date')
    )
    return Response([str(d) for d in dates], status=200)


@api_view(['GET'])
@permission_classes([IsTenantUser])
def roster_day(request, date_str):
    """The full published roster for one date, as everyone should see it.

    Each assignment is flagged ``is_you`` when it belongs to the person linked to
    the requesting login (``Persons.user``), which is what lets the UI highlight a
    member's own rows. A login with no linked person simply gets ``is_you`` false
    throughout and still sees the whole roster.
    """
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return Response({'error': 'Invalid date. Use YYYY-MM-DD.'}, status=400)

    rosters_qs = (
        scoped(Rosters, request)
        .filter(date=target_date)
        .select_related('event')
        .prefetch_related('assignments__person', 'assignments__role')
        .order_by('event__id')
    )
    if not rosters_qs.exists():
        return Response({'error': f'No roster found for {date_str}'}, status=404)

    own_person_id = getattr(getattr(request.user, 'person', None), 'pk', None)

    producer = None
    assistant_producer = None
    special_roles = {}
    events_payload = []
    for roster in rosters_qs:
        assignments = []
        # Saved arrangement first, so the published schedule reads in the same
        # order as the approved PDF rather than alphabetically.
        for a in sorted(roster.assignments.all(), key=lambda a: (a.display_order, a.pk)):
            entry = {
                'person_id': a.person_id,
                'name': f"{a.person.first_name} {a.person.last_name}".strip(),
                'role': a.role.name,
                'is_you': a.person_id == own_person_id,
            }
            # Leadership and special roles are day-level: they cover the whole
            # date, but they are stored against the first roster of the day, so
            # leaving them in that roster's list would read as if they were only
            # on duty for that one event. `saved_roster` already splits them out
            # this way — this keeps the published schedule agreeing with the
            # generator and the PDF rather than showing a longer event.
            role_name = a.role.name.lower()
            if role_name == 'producer':
                producer = entry
            elif role_name == 'assistant producer':
                assistant_producer = entry
            elif a.role.is_special_role:
                special_roles.setdefault(role_name, []).append(entry)
            else:
                assignments.append(entry)
        events_payload.append({
            'roster_id': roster.pk,
            'event_id': roster.event_id,
            'event_name': roster.event.name if roster.event else 'Unnamed event',
            'assignments': assignments,
        })

    return Response({
        'date': str(target_date),
        'linked_person_id': own_person_id,
        'producer': producer,
        'assistant_producer': assistant_producer,
        'special_roles': special_roles,
        'events': events_payload,
    }, status=200)


LEADERSHIP_ROLE_NAMES = ('producer', 'assistant producer')


@api_view(['GET'])
@permission_classes([CanSchedule])
def saved_roster(request, date_str):
    """The saved roster for one date, in the shape the generator emits.

    This is what lets the generator page reopen a date and show exactly what was
    saved — including the row arrangement, which comes back in the
    ``Assignment.display_order`` the scheduler dragged it into. Without it a reload
    would fall back to the roles' default order and the exported PDF would differ
    from the one they approved.

    404 when the date has never been saved, so the caller can tell "nothing here
    yet" from "here is an empty roster".
    """
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return Response({'error': 'Invalid date. Use YYYY-MM-DD.'}, status=400)

    rosters_qs = (
        scoped(Rosters, request)
        .filter(date=target_date)
        .select_related('event')
        .prefetch_related('assignments__person', 'assignments__role')
        .order_by('event__id')
    )
    if not rosters_qs.exists():
        return Response({'error': f'No saved roster for {date_str}'}, status=404)

    def person_name(person):
        return f"{person.first_name} {person.last_name}".strip()

    producer = None
    assistant_producer = None
    special_roles = {}
    events_payload = []
    everyone_assigned = set()

    for roster in rosters_qs:
        event_assignments = []
        # Meta.ordering on Assignment already sorts by display_order, but the
        # prefetched cache is a plain list, so sort explicitly rather than relying
        # on the queryset's ordering surviving prefetch.
        for assignment in sorted(
            roster.assignments.all(), key=lambda a: (a.display_order, a.pk)
        ):
            role = assignment.role
            person = assignment.person
            everyone_assigned.add(person.pk)
            entry = {'person_id': person.pk, 'name': person_name(person)}

            # Leadership and special roles are day-level: they live on the first
            # roster of the day but do not belong to that event's own list.
            if role.name.lower() == 'producer':
                producer = {'id': person.pk, 'name': person_name(person)}
            elif role.name.lower() == 'assistant producer':
                assistant_producer = {'id': person.pk, 'name': person_name(person)}
            elif role.is_special_role:
                special_roles.setdefault(role.name.lower(), []).append(entry)
            else:
                event_assignments.append({
                    'role': role.name,
                    'name': person_name(person),
                    'person_id': person.pk,
                })

        events_payload.append({
            'event_id': roster.event_id,
            'event_name': roster.event.name if roster.event else 'Unnamed event',
            'assignments': event_assignments,
        })

    available_count = scoped(Persons, request).filter(
        is_active=True, is_present=True
    ).count()

    return Response({
        'date': str(target_date),
        'metadata': {
            # The save time is the closest thing to "when this roster came to be";
            # the original generation timestamp is not kept.
            'generated_at': rosters_qs.first().updated_at.isoformat(),
            'total_people_available': available_count,
            'total_assignments': len(everyone_assigned),
        },
        'producer': producer,
        'assistant_producer': assistant_producer,
        'events': events_payload,
        'special_roles': special_roles,
        'saved': True,
    }, status=200)


@api_view(['GET'])
@permission_classes([CanSchedule])
def roster_statistics(request):
    """Per-person and per-role assignment counts for the current client.

    Query params:
      ``lookback_days`` (int, default 90, max 3650) — how far back to look.

    Counts saved assignments only, so it reflects the same history the generator
    rotates against.
    """
    raw = request.query_params.get('lookback_days', 90)
    try:
        lookback_days = int(raw)
    except (ValueError, TypeError):
        return Response({'error': 'The number of days to look back must be a whole number.'}, status=400)
    if not 1 <= lookback_days <= 3650:
        return Response(
            {'error': 'The number of days to look back must be between 1 and 3650.'}, status=400
        )

    stats = get_assignment_statistics(
        current_client(request), lookback_days=lookback_days
    )
    return Response(stats, status=200)


@api_view(['POST'])
@permission_classes([CanSchedule])
def generate_and_download_roster(request):
    """Render a roster payload to PDF and return it as a file download.

    Body: ``{"roster_data": <roster payload>}``. Renders whatever is posted — it does
    not read the database — so the PDF reflects the client's current on-screen edits.
    """
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
@permission_classes([IsClientAdmin])
def award_types(request):
    """List or create the client's award types (Day off, Gift, …)."""
    if request.method == 'GET':
        qs = scoped(AwardType, request)
        serializer = AwardTypeSerializer(qs, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'POST':
        serializer = AwardTypeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(client=current_client(request))
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsClientAdmin])
def award_type_detail(request, pk):
    """Fetch, update or delete an award type.

    Deletion is blocked by ``on_delete=PROTECT`` once awards of this type exist —
    deactivate it with ``is_active=False`` instead.
    """
    try:
        award_type = scoped(AwardType, request).get(pk=pk)
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
    """Parse ``YYYY-MM-DD`` leniently — returns None instead of raising."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


@api_view(['GET', 'POST'])
@permission_classes([IsClientAdmin])
def awards(request):
    """List (filtered, paginated) or grant awards.

    GET filters: ``person``, ``type``, ``from``, ``to`` (dates as YYYY-MM-DD).

    POST grants an award and *consumes* the recipient's streak: the current streak is
    snapshotted onto ``streak_at_award``, promoted to ``longest_streak`` if it's a
    record, then reset to zero. ``given_by`` and ``given_at`` are filled in server-side.

    The reset sticks because ``_recalculate_streak`` only counts attendance dated
    after the person's most recent award — so the recipient starts building again
    from their next event day.
    """
    if request.method == 'GET':
        qs = scoped(Award, request).select_related('person', 'award_type', 'given_by')

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
    serializer = AwardSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    person = serializer.validated_data['person']

    client = current_client(request)
    # Guard against awarding a person that belongs to another client.
    if person.client_id != getattr(client, 'id', None):
        return Response({'error': 'That team member could not be found — they may have been removed.'}, status=404)

    # Snapshot the streak *before* it resets, so the award shows the streak it earned.
    streak, _ = MemberStreak.objects.get_or_create(
        person=person, defaults={'client': client}
    )
    streak_snapshot = streak.current_streak

    given_by = request.user if request.user.is_authenticated else None
    if not serializer.validated_data.get('given_at'):
        serializer.validated_data['given_at'] = date.today()

    award = serializer.save(streak_at_award=streak_snapshot, given_by=given_by, client=client)

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak
    streak.current_streak = 0
    streak.save()

    return Response(AwardSerializer(award).data, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsClientAdmin])
def award_detail(request, pk):
    """Fetch, update or delete a single award. Deleting does not restore the streak."""
    try:
        award = scoped(Award, request).get(pk=pk)
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
@permission_classes([IsClientAdmin])
def award_stats(request):
    """Aggregate counts for the awards dashboard.

    Returns totals plus three breakdowns: ``by_type``, ``top_recipients`` (top 10)
    and ``by_month`` (chronological, ``YYYY-MM`` keys).
    """
    from django.db.models.functions import TruncMonth

    today = date.today()
    month_start = today.replace(day=1)
    qs = scoped(Award, request)

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
@permission_classes([IsClientAdmin])
def person_awards(request, pk):
    """Return all awards received by a single person."""
    if not scoped(Persons, request).filter(pk=pk).exists():
        return Response({"error": "Person not found"}, status=404)
    qs = (
        scoped(Award, request)
        .filter(person_id=pk)
        .select_related('award_type', 'given_by')
    )
    return Response(AwardSerializer(qs, many=True).data, status=200)


# ──────────────────────────────────────────
# Roster Feedback
# ──────────────────────────────────────────
def _recalculate_streak(person_id):
    """Recompute and persist the attendance streak for a single person.

    A streak counts **event days, not feedback rows**. There is one RosterFeedback
    row per (roster, person) and a day usually has several rosters, so the rows are
    first collapsed by date. A day counts as attended only if the person was present
    at every roster they were assigned to that day — a single absence marked while
    filling in feedback breaks the streak.

    A day whose feedback is only partly filled in is skipped — neither counted nor
    treated as a break. Feedback is submitted one roster at a time, so without this
    a half-recorded day would look fully attended between submissions and could
    ratchet ``longest_streak`` up on a day that ends up broken. Skipping also means
    a day nobody ever recorded doesn't silently end someone's streak.

    Only attendance recorded *after* the person's most recent award counts. Granting
    an award consumes the streak that earned it (see ``awards``), and without this
    cutoff the next feedback submission would recompute from full history and hand
    the streak straight back.

    ``longest_streak`` only ever ratchets upward, so trimming the current streak
    never erases a past record.
    """
    try:
        person = Persons.objects.get(pk=person_id)
    except Persons.DoesNotExist:
        return

    last_award_date = (
        Award.objects
        .filter(person_id=person_id)
        .order_by('-given_at')
        .values_list('given_at', flat=True)
        .first()
    )

    feedbacks = RosterFeedback.objects.filter(person=person).select_related('roster')
    if last_award_date:
        feedbacks = feedbacks.filter(roster__date__gt=last_award_date)

    # How many rosters the person is actually on each day, so we can tell a fully
    # recorded day from a half-recorded one.
    rosters_per_day = {
        row['roster__date']: row['n']
        for row in Assignment.objects
        .filter(person_id=person_id)
        .values('roster__date')
        .annotate(n=Count('roster_id', distinct=True))
    }

    # date -> (feedback rows seen, present at all of them)
    recorded = {}
    for fb in feedbacks:
        day = fb.roster.date
        seen, all_present = recorded.get(day, (0, True))
        recorded[day] = (seen + 1, all_present and fb.is_present)

    current_streak = 0
    for day in sorted(recorded, reverse=True):
        seen, all_present = recorded[day]
        if seen < rosters_per_day.get(day, seen):
            # Still being filled in — no verdict yet, so skip it rather than let a
            # half-entered day wipe out the streak the person has already built.
            continue
        if not all_present:
            break
        current_streak += 1

    streak, _ = MemberStreak.objects.get_or_create(
        person=person, defaults={'client_id': person.client_id}
    )
    if current_streak > streak.longest_streak:
        streak.longest_streak = current_streak
    streak.current_streak = current_streak
    streak.save()


@api_view(['GET'])
@permission_classes([CanSchedule])
def person_streaks(request):
    """Return current and longest attendance streak for every active member."""
    persons = scoped(Persons, request).filter(is_active=True).select_related('streak')
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
@permission_classes([CanSchedule])
def roster_persons(request, roster_id):
    """Return all persons assigned to a roster with their current feedback status.

    De-duplicates people assigned to more than one role on the same roster, keeping
    the first role seen. People with no feedback row yet default to present.
    """
    try:
        roster = scoped(Rosters, request).get(pk=roster_id)
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
@permission_classes([CanSchedule])
def submit_feedback(request, roster_id):
    """Bulk create/update per-person feedback for one roster (admin path).

    Expects: ``{"feedback": [{"person_id": 1, "is_present": true, "feedback": "...",
    "rating": 4, "feedback_category": "teamwork"}, ...]}``

    Person IDs outside the caller's client are silently skipped. Every touched
    person's streak is recomputed afterwards. Compare ``feedback_share_submit``,
    which is the public one-time-link path and writes one shared note to everyone.
    """
    try:
        roster = scoped(Rosters, request).get(pk=roster_id)
    except Rosters.DoesNotExist:
        return Response({"error": "Roster not found"}, status=404)

    items = request.data.get('feedback', [])
    if not items:
        return Response({"error": "No feedback data provided"}, status=400)

    client = current_client(request)
    # Only accept feedback for persons belonging to this client.
    requested_ids = [item.get('person_id') for item in items if item.get('person_id')]
    valid_ids = set(
        scoped(Persons, request).filter(id__in=requested_ids).values_list('id', flat=True)
    )
    created = 0
    updated = 0
    person_ids = []
    for item in items:
        person_id = item.get('person_id')
        if not person_id or int(person_id) not in valid_ids:
            continue
        obj, was_created = RosterFeedback.objects.update_or_create(
            roster=roster,
            person_id=person_id,
            defaults={
                'client': client,
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
@permission_classes([CanSchedule])
def roster_feedback(request, roster_id):
    """Return every feedback entry recorded against a single roster."""
    qs = scoped(RosterFeedback, request).filter(
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
        .filter(date=link.date, client_id=link.client_id)
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
@permission_classes([CanSchedule])
def create_feedback_share_link(request):
    """Create a one-time share link for a roster date. Authenticated admin endpoint.

    Body: { "date": "YYYY-MM-DD" }
    Returns: { token, date, share_url }
    """
    date_str = request.data.get('date')
    if not date_str:
        return Response({'error': 'Choose a date first.'}, status=400)
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'error': 'Invalid date format'}, status=400)

    client = current_client(request)
    if not scoped(Rosters, request).filter(date=target_date).exists():
        return Response(
            {'error': f'No saved roster for {date_str}. Save the roster before generating a share link.'},
            status=400,
        )

    # Once feedback has been collected for a date, don't allow another link —
    # the day's attendance is final.
    if scoped(RosterFeedback, request).filter(roster__date=target_date).exists():
        return Response(
            {'error': f'Feedback has already been collected for {date_str}.'},
            status=409,
        )

    token = secrets.token_urlsafe(32)
    link = FeedbackShareLink.objects.create(
        token=token,
        date=target_date,
        client=client,
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
@permission_classes([AllowAny])
def feedback_share_get(request, token):
    """Public: fetch the form data for a share link."""
    try:
        link = FeedbackShareLink.objects.get(token=token)
    except FeedbackShareLink.DoesNotExist:
        return Response({'error': 'This link is not valid. Ask whoever shared it to send a new one.'}, status=404)
    if link.is_used:
        return Response({'error': 'This link has already been used.'}, status=410)
    return Response(_build_share_payload(link), status=200)


@api_view(['POST'])
@permission_classes([AllowAny])
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
        return Response({'error': 'This link is not valid. Ask whoever shared it to send a new one.'}, status=404)
    if link.is_used:
        return Response({'error': 'This link has already been used.'}, status=410)

    attendance = request.data.get('attendance', [])
    global_feedback = request.data.get('global_feedback', '') or ''
    global_recommendations = request.data.get('global_recommendations', '') or ''

    presence_by_person = {}
    for item in attendance:
        pid = item.get('person_id')
        if pid is None:
            continue
        presence_by_person[int(pid)] = bool(item.get('is_present', True))

    rosters_for_day = list(Rosters.objects.filter(date=link.date, client_id=link.client_id))
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
            global_recommendations=global_recommendations,
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
                        'client_id': link.client_id,
                        'is_present': is_present,
                        'feedback': global_feedback,
                        'recommendations': global_recommendations,
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
@permission_classes([CanSchedule])
def feedback_summary(request):
    """Per-date summary of collected feedback: who was present and the day's note.

    Used by the admin feedback page to list already-collected days and to know
    which dates should no longer offer link generation.
    """
    feedbacks = (
        scoped(RosterFeedback, request)
        .select_related('person', 'roster')
        .order_by('-roster__date')
    )

    # Day-level note preferred from the share link used for that date.
    used_links = scoped(FeedbackShareLink, request).filter(is_used=True)
    link_notes = {
        str(link.date): link.global_feedback
        for link in used_links
        if link.global_feedback
    }
    link_recommendations = {
        str(link.date): link.global_recommendations
        for link in used_links
        if link.global_recommendations
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
                'recommendations': set(),
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
        if fb.recommendations:
            entry['recommendations'].add(fb.recommendations)
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
            'recommendations': link_recommendations.get(key) or ' / '.join(sorted(entry['recommendations'])),
            'submitted_at': entry['submitted_at'].isoformat(),
        })
    result.sort(key=lambda x: x['date'], reverse=True)
    return Response(result, status=200)


@api_view(['PATCH'])
@permission_classes([CanSchedule])
def update_day_feedback(request, date_str):
    """Edit the day-level feedback note and recommendations for a collected date.

    Updates both possible sources the summary reads from so the change shows up
    regardless of how the day was collected:
      * the used FeedbackShareLink for that date (its global_* fields), and
      * every RosterFeedback row for that date's rosters.

    Caveat: the second step is a blanket ``.update()``, so any per-person notes
    captured via ``submit_feedback`` for that date are overwritten with the day-level
    text. That is fine for days collected through a share link (where the note was
    already shared), but lossy for days edited person-by-person.
    """
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return Response({'error': 'Invalid date. Use YYYY-MM-DD.'}, status=400)

    feedback = (request.data.get('feedback') or '').strip()
    recommendations = (request.data.get('recommendations') or '').strip()

    affected = scoped(RosterFeedback, request).filter(roster__date=target_date)
    if not affected.exists():
        return Response(
            {'error': f'No collected feedback found for {date_str}.'},
            status=404,
        )

    affected.update(feedback=feedback, recommendations=recommendations)
    scoped(FeedbackShareLink, request).filter(date=target_date, is_used=True).update(
        global_feedback=feedback,
        global_recommendations=recommendations,
    )

    return Response({
        'date': date_str,
        'feedback': feedback,
        'recommendations': recommendations,
    }, status=200)


# ──────────────────────────────────────────
# Tenant user management — a client admin managing their own client's logins.
# Distinct from the admin_client_users view below, which is the platform admin
# reaching into any client.
# ──────────────────────────────────────────
TENANT_ROLES = {User.ROLE_ADMIN, User.ROLE_SCHEDULER, User.ROLE_MEMBER}


def _client_user_payload(user):
    person = getattr(user, 'person', None)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'is_active': user.is_active,
        'person_id': person.pk if person else None,
    }


def _would_orphan_client(client_id, user, *, new_role=None, deleting=False):
    """True if this change would leave the client with no active admin.

    A client with no admin can't manage its own users or data any more and needs a
    platform admin to dig it out, so both role changes and deletions are checked.
    """
    if not deleting and new_role == User.ROLE_ADMIN:
        return False
    if user.role != User.ROLE_ADMIN or not user.is_active:
        return False
    others = User.objects.filter(
        client_id=client_id, role=User.ROLE_ADMIN, is_active=True,
    ).exclude(pk=user.pk)
    return not others.exists()


@api_view(['GET', 'POST'])
@permission_classes([IsClientAdmin])
def client_users(request):
    """List or create logins for the requesting admin's own client.

    POST body: ``{username, password, role, email?, first_name?, last_name?,
    person_id?}``. ``role`` must be one of admin/scheduler/member and defaults to
    member — the least privilege, so a typo can't mint an admin.

    ``person_id`` optionally links the new login to an existing team member, which
    is what makes their own assignments highlight on the schedule view.
    """
    client = current_client(request)

    if request.method == 'GET':
        users = (
            User.objects.filter(client=client)
            .select_related('person')
            .order_by('username')
        )
        return Response([_client_user_payload(u) for u in users], status=200)

    role = (request.data.get('role') or User.ROLE_MEMBER).strip()
    if role not in TENANT_ROLES:
        return Response(
            {'error': 'Choose whether this person is an admin, a scheduler or a member.'},
            status=400,
        )

    person, err = _resolve_person_link(request, request.data.get('person_id'))
    if err:
        return err

    with transaction.atomic():
        user, err = _create_client_user(client, request.data, role=role)
        if err:
            transaction.set_rollback(True)
            return err
        if person:
            person.user = user
            person.save(update_fields=['user'])

    user.refresh_from_db()
    return Response(_client_user_payload(user), status=201)


def _resolve_person_link(request, person_id, *, exclude_user_id=None):
    """Validate an optional person_id for linking. Returns (person_or_None, error)."""
    if person_id in (None, ''):
        return None, None
    try:
        person = scoped(Persons, request).get(pk=person_id)
    except (Persons.DoesNotExist, ValueError, TypeError):
        return None, Response({'error': 'That team member could not be found — they may have been removed.'}, status=404)
    if person.user_id and person.user_id != exclude_user_id:
        return None, Response(
            {'error': 'That member is already linked to another login'}, status=409
        )
    return person, None


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsClientAdmin])
def client_user_detail(request, pk):
    """Retrieve, update or delete one login belonging to the admin's own client.

    PATCH accepts name/email/role/is_active/password and ``person_id`` (pass null
    to unlink). Both PATCH and DELETE refuse to remove the client's last active
    admin, which would lock the tenant out of its own account management.
    """
    client = current_client(request)
    try:
        user = User.objects.select_related('person').get(pk=pk, client=client)
    except User.DoesNotExist:
        return Response({'error': 'That login could not be found — it may have been removed.'}, status=404)

    if request.method == 'GET':
        return Response(_client_user_payload(user), status=200)

    if request.method == 'DELETE':
        if user.pk == request.user.pk:
            return Response({'error': 'You cannot delete your own account'}, status=400)
        if _would_orphan_client(client.id, user, deleting=True):
            return Response(
                {'error': 'This is the last admin for this client. '
                          'Promote someone else before deleting this account.'},
                status=409,
            )
        user.delete()
        return Response({'message': 'User deleted'}, status=204)

    # PATCH
    new_role = request.data.get('role')
    if new_role is not None:
        new_role = str(new_role).strip()
        if new_role not in TENANT_ROLES:
            return Response(
                {'error': 'Choose whether this person is an admin, a scheduler or a member.'},
                status=400,
            )
        if _would_orphan_client(client.id, user, new_role=new_role):
            return Response(
                {'error': 'This is the last admin for this client. '
                          'Promote someone else before changing this role.'},
                status=409,
            )
        user.role = new_role

    if 'is_active' in request.data:
        make_active = bool(request.data.get('is_active'))
        if not make_active:
            if user.pk == request.user.pk:
                return Response(
                    {'error': 'You cannot deactivate your own account'}, status=400
                )
            if _would_orphan_client(client.id, user, deleting=True):
                return Response(
                    {'error': 'This is the last admin for this client. '
                              'Promote someone else before deactivating this account.'},
                    status=409,
                )
        user.is_active = make_active

    for field in ('first_name', 'last_name', 'email'):
        if field in request.data:
            setattr(user, field, request.data.get(field) or '')

    if request.data.get('password'):
        user.set_password(request.data['password'])

    if 'person_id' in request.data:
        person_id = request.data.get('person_id')
        if person_id in (None, ''):
            Persons.objects.filter(user=user).update(user=None)
        else:
            person, err = _resolve_person_link(
                request, person_id, exclude_user_id=user.pk
            )
            if err:
                return err
            Persons.objects.filter(user=user).exclude(pk=person.pk).update(user=None)
            person.user = user
            person.save(update_fields=['user'])

    user.save()
    user.refresh_from_db()
    return Response(_client_user_payload(user), status=200)


# ──────────────────────────────────────────
# Platform superadmin — client (tenant) management
# Only accessible to platform admins (client=None, is_superuser).
# ──────────────────────────────────────────
def _unique_client_slug(name, preferred=None):
    """Slugify ``preferred`` (falling back to ``name``), suffixing -2, -3, … to make
    it globally unique across clients."""
    base = slugify(preferred or name) or 'client'
    slug = base
    i = 2
    while Client.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _create_client_user(client, data, is_staff=True, role=None):
    """Create a login for a client. Returns (user, error_response).

    ``role`` defaults to admin, which is right for the *first* account created
    alongside a new client — somebody has to be able to administer it. Callers
    provisioning additional users should pass an explicit role.
    """
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return None, Response(
            {'error': 'Enter both a username and a password for this login.'}, status=400
        )
    if User.objects.filter(username=username).exists():
        return None, Response(
            {'error': 'That username is already taken. Choose a different one.'}, status=409
        )
    user = User.objects.create_user(
        username=username,
        email=data.get('email') or '',
        password=password,
        first_name=data.get('first_name') or '',
        last_name=data.get('last_name') or '',
        client=client,
        is_staff=is_staff,
        role=role or User.ROLE_ADMIN,
    )
    return user, None


@api_view(['GET', 'POST'])
@permission_classes([IsPlatformAdmin])
def admin_clients(request):
    """List all clients, or create a new client (optionally with its first admin)."""
    if request.method == 'GET':
        qs = Client.objects.all()
        return Response(ClientSerializer(qs, many=True).data, status=200)

    name = (request.data.get('name') or '').strip()
    if not name:
        return Response({'error': 'Enter a name for the organisation.'}, status=400)
    slug = _unique_client_slug(name, (request.data.get('slug') or '').strip())

    admin = request.data.get('admin') or {}
    has_admin = bool((admin.get('username') or '').strip())

    with transaction.atomic():
        client = Client.objects.create(name=name, slug=slug)
        created_admin = None
        if has_admin:
            created_admin, err = _create_client_user(client, admin)
            if err:
                transaction.set_rollback(True)
                return err

    data = ClientSerializer(client).data
    if created_admin:
        data['admin'] = {'id': created_admin.id, 'username': created_admin.username}
    return Response(data, status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsPlatformAdmin])
def admin_client_detail(request, pk):
    """Retrieve, update (name/slug/active), or delete a client and all its data."""
    try:
        client = Client.objects.get(pk=pk)
    except Client.DoesNotExist:
        return Response({'error': 'That client could not be found — it may have been removed.'}, status=404)

    if request.method == 'GET':
        return Response(ClientSerializer(client).data, status=200)

    if request.method == 'PATCH':
        name = request.data.get('name')
        if name is not None:
            name = name.strip()
            if not name:
                return Response({'error': 'Enter a name for the organisation.'}, status=400)
            client.name = name
        if 'is_active' in request.data:
            client.is_active = bool(request.data.get('is_active'))
        if request.data.get('slug'):
            new_slug = slugify(request.data['slug'])
            if Client.objects.filter(slug=new_slug).exclude(pk=client.pk).exists():
                return Response({'error': 'That web address is already taken by another client. Choose a different one.'}, status=409)
            client.slug = new_slug
        client.save()
        return Response(ClientSerializer(client).data, status=200)

    # DELETE — cascades to every row owned by the client.
    client.delete()
    return Response({'message': 'Client and all its data deleted'}, status=204)


@api_view(['GET', 'POST'])
@permission_classes([IsPlatformAdmin])
def admin_client_users(request, pk):
    """List or create login accounts for a specific client.

    The platform-admin counterpart to ``client_users``. ``role`` may be given on
    POST and defaults to admin here, since this is usually how a client gets its
    first administrator.
    """
    try:
        client = Client.objects.get(pk=pk)
    except Client.DoesNotExist:
        return Response({'error': 'That client could not be found — it may have been removed.'}, status=404)

    if request.method == 'GET':
        return Response([
            {
                'id': u.id, 'username': u.username, 'email': u.email,
                'first_name': u.first_name, 'last_name': u.last_name,
                'is_staff': u.is_staff, 'role': u.role, 'is_active': u.is_active,
            }
            for u in client.users.all()
        ], status=200)

    role = (request.data.get('role') or User.ROLE_ADMIN).strip()
    if role not in TENANT_ROLES:
        return Response(
            {'error': 'Choose whether this person is an admin, a scheduler or a member.'},
            status=400,
        )

    user, err = _create_client_user(client, request.data, role=role)
    if err:
        return err
    return Response(
        {'id': user.id, 'username': user.username, 'role': user.role}, status=201
    )

