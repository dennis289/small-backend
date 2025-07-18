from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime


def export_roster_pdf(roster_data: dict):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=50,
        bottomMargin=50
    )
    styles = getSampleStyleSheet()
    elements = []

    # Custom styles to match the document format
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=16,
        spaceAfter=20,
        alignment=TA_CENTER,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )

    # Main header - exact format from the document
    roster_date = roster_data.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        formatted_date = datetime.strptime(roster_date, '%Y-%m-%d').strftime('%dth %B %y').upper()
        # Handle ordinal suffixes correctly
        day = int(roster_date.split('-')[2])
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["th", "st", "nd", "rd", "th", "th", "th", "th", "th", "th"][day % 10]
        formatted_date = datetime.strptime(roster_date, '%Y-%m-%d').strftime(f'%d{suffix} %B %y').upper()
    except:
        formatted_date = roster_date.upper()
    
    title = Paragraph(f"MEDIA DEPT ROSTER {formatted_date}", title_style)
    elements.append(title)
    elements.append(Spacer(1, 20))

    # Main roster table - matching the exact structure from the document
    # Get leadership info
    if 'leadership' in roster_data:
        producer_name = roster_data['leadership'].get('producer', {}).get('name', '')
        assistant_name = roster_data['leadership'].get('assistant_producer', {}).get('name', '')
    else:
        producer_name = roster_data.get('producer', {}).get('name', '') if isinstance(roster_data.get('producer'), dict) else roster_data.get('producer', '')
        assistant_name = roster_data.get('assistant_producer', {}).get('name', '') if isinstance(roster_data.get('assistant_producer'), dict) else roster_data.get('assistant_producer', '')

    # Create the main table data structure matching the document
    table_data = [
        ['SERVICE PRODUCER', producer_name or 'Not Assigned'],
        ['ASSISTANT PRODUCER', assistant_name or 'Not Assigned'],
        ['', ''],  # Empty row for spacing
    ]

    # Add service assignments in the document format
    for service in roster_data.get('services', []):
        # Add service header
        table_data.append([f"{service['service_name'].upper()}", ''])
        
        # Add assignments for this service
        for assignment in service.get('assignments', []):
            table_data.append([assignment['role'], assignment['name']])
        
        # Add spacing
        table_data.append(['', ''])

    # Add hospitality section
    hospitality_names = []
    if 'special_roles' in roster_data and roster_data['special_roles'].get('hospitality'):
        hospitality_names = [person.get('name', '') for person in roster_data['special_roles']['hospitality']]
    elif 'hospitality' in roster_data and roster_data['hospitality']:
        hospitality_names = roster_data['hospitality']
    
    if hospitality_names:
        table_data.append(['HOSPITALITY', ''])
        for name in hospitality_names:
            table_data.append(['', name])
        table_data.append(['', ''])

    # Add social media section
    social_media_names = []
    if 'special_roles' in roster_data and roster_data['special_roles'].get('social_media'):
        social_media_names = [person.get('name', '') for person in roster_data['special_roles']['social_media']]
    elif 'social_media' in roster_data and roster_data['social_media']:
        social_media_names = roster_data['social_media']
    
    if social_media_names:
        table_data.append(['SOCIAL MEDIA', ''])
        for name in social_media_names:
            table_data.append(['', name])

    # Create the main table with exact styling from the document
    main_table = Table(table_data, colWidths=[3*inch, 3*inch])
    
    # Table styling to match the document exactly
    table_style = [
        # Grid lines
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        
        # Font settings
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        
        # Alignment
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]

    # Add bold formatting for headers and section titles
    row_index = 0
    for row in table_data:
        if row[0] in ['SERVICE PRODUCER', 'ASSISTANT PRODUCER'] or \
           any(section in row[0] for section in ['SERVICE', 'HOSPITALITY', 'SOCIAL MEDIA']) and row[0] != '':
            table_style.append(('FONTNAME', (0, row_index), (0, row_index), 'Helvetica-Bold'))
        row_index += 1

    main_table.setStyle(TableStyle(table_style))
    elements.append(main_table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
