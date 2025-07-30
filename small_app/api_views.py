from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from datetime import datetime, date
import json
from .serializers import *
from .models import *
from .scheduler import generate_roster, get_assignment_statistics
from .pdf import export_roster_pdf

User = get_user_model()

# Authentication endpoints
@api_view(['POST'])
def api_login(request):
    """
    Login endpoint for Flutter app
    Expected format: {"email": "user@example.com", "password": "password"}
    Returns: {"token": "jwt_token", "user": {...}}
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            }
        }, status=status.HTTP_200_OK)
    
    return Response({
        'error': 'Invalid credentials'
    }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def api_signup(request):
    """
    Signup endpoint for Flutter app
    """
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            }
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# People endpoints
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_people(request):
    """
    GET: List all people
    POST: Create a new person
    """
    if request.method == 'GET':
        people = Persons.objects.all().order_by('-created_at')
        serializer = PersonsSerializer(people, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'POST':
        # Handle both full name and separate first/last name
        data = request.data.copy()
        if 'name' in data and 'first_name' not in data:
            # Split full name into first and last name
            name_parts = data['name'].split(' ', 1)
            data['first_name'] = name_parts[0]
            data['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
        
        serializer = PersonsSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_person_detail(request, pk):
    """
    GET: Retrieve a person
    PUT: Update a person
    DELETE: Delete a person
    """
    try:
        person = Persons.objects.get(pk=pk)
    except Persons.DoesNotExist:
        return Response({'error': 'Person not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = PersonsSerializer(person)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PUT':
        # Handle both full name and separate first/last name
        data = request.data.copy()
        if 'name' in data and 'first_name' not in data:
            # Split full name into first and last name
            name_parts = data['name'].split(' ', 1)
            data['first_name'] = name_parts[0]
            data['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
        
        serializer = PersonsSerializer(person, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        person.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Roles endpoints
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_roles(request):
    """
    GET: List all roles
    POST: Create a new role
    """
    if request.method == 'GET':
        roles = Roles.objects.all().order_by('-created_at')
        serializer = RolesSerializer(roles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'POST':
        serializer = RolesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_role_detail(request, pk):
    """
    GET: Retrieve a role
    PUT: Update a role
    DELETE: Delete a role
    """
    try:
        role = Roles.objects.get(pk=pk)
    except Roles.DoesNotExist:
        return Response({'error': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = RolesSerializer(role)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PUT':
        serializer = RolesSerializer(role, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Services endpoints
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_services(request):
    """
    GET: List all services
    POST: Create a new service
    """
    if request.method == 'GET':
        services = Services.objects.all().order_by('-created_at')
        serializer = ServicesSerializer(services, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'POST':
        serializer = ServicesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_service_detail(request, pk):
    """
    GET: Retrieve a service
    PUT: Update a service
    DELETE: Delete a service
    """
    try:
        service = Services.objects.get(pk=pk)
    except Services.DoesNotExist:
        return Response({'error': 'Service not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = ServicesSerializer(service)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PUT':
        serializer = ServicesSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Rosters endpoints
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_rosters(request):
    """
    GET: List all rosters
    POST: Create a new roster
    """
    if request.method == 'GET':
        rosters = Rosters.objects.all().order_by('-created_at')
        serializer = RostersSerializer(rosters, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'POST':
        serializer = RostersSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_roster_detail(request, pk):
    """
    GET: Retrieve a roster
    PUT: Update a roster
    DELETE: Delete a roster
    """
    try:
        roster = Rosters.objects.get(pk=pk)
    except Rosters.DoesNotExist:
        return Response({'error': 'Roster not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = RostersSerializer(roster)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'PUT':
        serializer = RostersSerializer(roster, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        roster.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Roster Generation endpoint
@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Temporarily disable auth for testing
def api_generate_roster(request):
    """
    Generate a new roster for a given date
    Expected format: {"date": "2024-01-01", "members": [1, 2, 3], "is_present": false}
    """
    try:
        target_date_str = request.data.get('date')
        members_to_exclude = request.data.get('members', [])
        is_present = request.data.get('is_present', False)
        
        if not target_date_str:
            return Response({'error': 'Date is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Parse the date
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update member presence status
        if members_to_exclude:
            Persons.objects.filter(id__in=members_to_exclude).update(is_present=is_present)
            # Set all others to present if we're marking some as absent
            if not is_present:
                Persons.objects.exclude(id__in=members_to_exclude).update(is_present=True)
        
        # Generate the roster
        roster_data = generate_roster(target_date)
        
        return Response(roster_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Save Roster endpoint
@api_view(['POST'])
@permission_classes([])  # Remove all permission classes for testing
@authentication_classes([])  # Remove all authentication classes for testing
def api_save_roster(request):
    """
    Save a generated roster to the database
    Expected format: {"date": "2024-01-01", "data": {...}}
    """
    try:
        print(f"DEBUG: Request type: {type(request)}")
        print(f"DEBUG: Request data: {request.data}")
        
        # Convert DRF request to Django request if needed for compatibility
        django_request = getattr(request, '_request', request)
        print(f"DEBUG: Django request type: {type(django_request)}")
        
        target_date_str = request.data.get('date')
        roster_data = request.data.get('data')
        
        print(f"DEBUG: About to validate inputs...")
        
        if not target_date_str:
            return Response({'error': 'Date is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not roster_data:
            return Response({'error': 'Roster data is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate roster structure
        if not isinstance(roster_data, dict):
            return Response({'error': 'Roster data must be a valid object'}, status=status.HTTP_400_BAD_REQUEST)
        
        if 'services' not in roster_data:
            return Response({'error': 'Roster must contain services data'}, status=status.HTTP_400_BAD_REQUEST)
        
        print(f"DEBUG: About to parse date...")
        
        # Parse the date
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
        
        print(f"DEBUG: About to save to database...")
        
        # Return success without actually saving for now to isolate the issue
        return Response({
            'message': 'Test successful - no database operations performed',
            'debug': 'Reached end of function without error'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        print(f"DEBUG: Exception occurred: {str(e)}")
        print(f"DEBUG: Exception type: {type(e)}")
        import traceback
        print(f"DEBUG: Traceback: {traceback.format_exc()}")
        return Response({'error': str(e), 'debug': 'Exception in api_save_roster'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# PDF Export endpoint
@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Temporarily disable auth for testing
def api_export_roster_pdf(request):
    """
    Export roster as PDF
    Expected format: {"roster_data": {...}, "date": "2024-01-01"}
    """
    try:
        roster_data = request.data.get('roster_data')
        target_date_str = request.data.get('date')
        
        if not roster_data or not target_date_str:
            return Response({'error': 'Roster data and date are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Parse the date
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create a mock roster object for PDF generation
        class MockRoster:
            def __init__(self, data, date):
                self.date = date
                # Handle both new structured format and legacy format
                if 'leadership' in data:
                    # New format
                    self.producer_name = data.get('leadership', {}).get('producer', {}).get('name', '')
                    self.assistant_producer_name = data.get('leadership', {}).get('assistant_producer', {}).get('name', '')
                else:
                    # Legacy format
                    self.producer_name = data.get('producer', {}).get('name', '') if isinstance(data.get('producer'), dict) else data.get('producer', '')
                    self.assistant_producer_name = data.get('assistant_producer', {}).get('name', '') if isinstance(data.get('assistant_producer'), dict) else data.get('assistant_producer', '')
                
                self.services_data = data.get('services', [])
                
                # Handle hospitality - both new and legacy formats
                if 'special_roles' in data:
                    self.hospitality = [person.get('name', '') for person in data.get('special_roles', {}).get('hospitality', [])]
                    self.social_media = [person.get('name', '') for person in data.get('special_roles', {}).get('social_media', [])]
                else:
                    self.hospitality = data.get('hospitality', [])
                    self.social_media = data.get('social_media', [])
        
        mock_roster = MockRoster(roster_data, target_date)
        
        # Generate PDF (you'll need to update the PDF generation function)
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from io import BytesIO
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title = Paragraph(
            f"MEDIA DEPT. DUTY ROSTER {target_date.strftime('%d %b %Y').upper()}",
            styles['Title']
        )
        elements.append(title)
        elements.append(Spacer(1, 12))

        # Producer Info
        producer_info = [
            ['SERVICE PRODUCER', mock_roster.producer_name],
            ['ASSISTANT PRODUCER', mock_roster.assistant_producer_name]
        ]
        producer_table = Table(producer_info, colWidths=[200, 200])
        producer_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTSIZE', (0,0), (-1,0), 14),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ]))
        elements.append(producer_table)
        elements.append(Spacer(1, 18))

        # Services
        for service_data in mock_roster.services_data:
            service_title = Paragraph(f"{service_data['service_name'].upper()}", styles['Heading2'])
            elements.append(service_title)
            elements.append(Spacer(1, 6))

            table_data = [['NAME', 'AREA OF SERVICE']]
            for assignment in service_data.get('assignments', []):
                table_data.append([assignment['name'], assignment['role']])

            service_table = Table(table_data, colWidths=[200, 200])
            service_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ]))
            elements.append(service_table)
            elements.append(Spacer(1, 12))

        # Special roles
        if mock_roster.hospitality:
            elements.append(Paragraph("HOSPITALITY", styles['Heading2']))
            elements.append(Spacer(1, 6))
            hospitality_data = [['NAME']]
            for person in mock_roster.hospitality:
                hospitality_data.append([person])
            
            hospitality_table = Table(hospitality_data, colWidths=[400])
            hospitality_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ]))
            elements.append(hospitality_table)
            elements.append(Spacer(1, 12))

        if mock_roster.social_media:
            elements.append(Paragraph("SOCIAL MEDIA", styles['Heading2']))
            elements.append(Spacer(1, 6))
            social_data = [['NAME']]
            for person in mock_roster.social_media:
                social_data.append([person])
            
            social_table = Table(social_data, colWidths=[400])
            social_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ]))
            elements.append(social_table)

        doc.build(elements)
        pdf_data = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="roster_{target_date.strftime("%Y_%m_%d")}.pdf"'
        
        return response
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Assignment Statistics endpoint
@api_view(['GET'])
def api_assignment_statistics(request):
    """
    Get assignment statistics for roster rotation analysis
    Query parameters:
    - days: Number of days to look back (default: 90)
    """
    try:
        lookback_days = int(request.GET.get('days', 90))
        
        if lookback_days < 1 or lookback_days > 365:
            return Response(
                {'error': 'Days parameter must be between 1 and 365'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        statistics = get_assignment_statistics(lookback_days)
        
        return Response(statistics, status=status.HTTP_200_OK)
        
    except ValueError:
        return Response(
            {'error': 'Invalid days parameter. Must be a number.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
