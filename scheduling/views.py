import logging
from datetime import datetime

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from small_app.models import Rosters
from small_app.serializers import AssignmentSerializer
from small_app.pdf import export_roster_pdf
from .services import generate_roster, get_assignment_statistics

logger = logging.getLogger(__name__)


@api_view(['POST'])
def generate_roster_view(request):
    """Generate (and optionally save) a roster for a given date.

    Body: { "date": "YYYY-MM-DD", "save_to_db": true }
    """
    date_str = request.data.get('date')
    save_to_db = request.data.get('save_to_db', True)

    if not date_str:
        return Response(
            {'error': 'date is required (YYYY-MM-DD)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        roster_data = generate_roster(target_date, save_to_db=save_to_db)
        return Response(roster_data, status=status.HTTP_201_CREATED)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("Error generating roster for %s", date_str)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def regenerate_roster_view(request, date_str):
    """Delete the existing roster for a date and regenerate it.

    Useful when attendance has changed after the initial generation.
    """
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    deleted_count, _ = Rosters.objects.filter(date=target_date).delete()
    if deleted_count:
        logger.info("Cleared %d existing roster(s) for %s before regenerating", deleted_count, date_str)

    try:
        roster_data = generate_roster(target_date, save_to_db=True)
        return Response(roster_data, status=status.HTTP_200_OK)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("Error regenerating roster for %s", date_str)
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def roster_for_date_view(request, date_str):
    """Return all saved roster entries (with assignments) for a specific date."""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rosters = (
        Rosters.objects
        .filter(date=target_date)
        .select_related('event')
        .prefetch_related('assignments__person', 'assignments__role')
    )

    if not rosters.exists():
        return Response(
            {'error': f'No roster found for {date_str}'},
            status=status.HTTP_404_NOT_FOUND,
        )

    result = []
    for roster in rosters:
        result.append({
            'roster_id': roster.pk,
            'event': roster.event.name if roster.event else None,
            'date': str(roster.date),
            'assignments': AssignmentSerializer(roster.assignments.all(), many=True).data,
        })

    return Response(result, status=status.HTTP_200_OK)


@api_view(['DELETE'])
def delete_roster_for_date_view(request, date_str):
    """Delete all roster entries and their assignments for a specific date."""
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    deleted_count, _ = Rosters.objects.filter(date=target_date).delete()
    return Response(
        {'message': f'Deleted {deleted_count} roster(s) for {date_str}'},
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
def roster_statistics_view(request):
    """Return per-person and per-role assignment statistics.

    Query params:
      lookback_days (int, default 90) — how far back to look
    """
    try:
        lookback_days = int(request.query_params.get('lookback_days', 90))
    except (ValueError, TypeError):
        return Response(
            {'error': 'lookback_days must be an integer'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    stats = get_assignment_statistics(lookback_days=lookback_days)
    return Response(stats, status=status.HTTP_200_OK)


@api_view(['POST'])
def export_roster_pdf_view(request):
    """Generate and return a PDF for the supplied roster data.

    Body: { "roster_data": { ...same shape as generate response... } }
    """
    roster_data = request.data.get('roster_data')
    if not roster_data:
        return Response(
            {'error': "'roster_data' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        pdf_bytes = export_roster_pdf(roster_data)
    except Exception as e:
        logger.exception("Error generating PDF")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    date_str = roster_data.get('date', 'roster')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="roster_{date_str}.pdf"'
    return response
