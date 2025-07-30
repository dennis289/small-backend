from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def export_roster_pdf(roster):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph(
        f"MEDIA DEPT. DUTY ROSTER {roster.date.strftime('%d %b %Y').upper()}",
        styles['Title']
    )
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Producer Info Table
    producer_info = [
        ['SERVICE PRODUCER', getattr(roster.producer, 'name', '')],
        ['ASSISTANT PRODUCER', getattr(roster.assistant_producer, 'name', '') if hasattr(roster, 'assistant_producer') else '']
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

    # Group assignments by service time
    assignments_by_service = {}
    for assignment in roster.assignments.all():
        service_name = assignment.service_time.name
        if service_name not in assignments_by_service:
            assignments_by_service[service_name] = []
        assignments_by_service[service_name].append(
            (assignment.person.name, assignment.role.name)
        )

    # Add service tables
    for service_name, assignments in assignments_by_service.items():
        service_title = Paragraph(f"{service_name.upper()}", styles['Heading2'])
        elements.append(service_title)
        elements.append(Spacer(1, 6))

        table_data = [['NAME', 'AREA OF SERVICE']]
        table_data.extend(assignments)

        service_table = Table(table_data, colWidths=[200, 200])
        service_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ]))
        elements.append(service_table)
        elements.append(Spacer(1, 12))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf