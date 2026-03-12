from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, ListFlowable, ListItem
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT


def _ordinal(n):
    """Return ordinal string for an integer (1 -> '1st', 2 -> '2nd', etc.)."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return str(n), suffix


def _format_roster_date(date_str):
    """Convert 'YYYY-MM-DD' to '1st MAR 2026' style with superscript ordinal."""
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
    except (ValueError, TypeError):
        return str(date_str)
    day_num, suffix = _ordinal(dt.day)
    month = dt.strftime("%b").upper()
    year = dt.year
    return f"{day_num}<super><font size=7>{suffix}</font></super> {month}  {year}"


def _format_event_heading(event_name):
    """
    Try to superscript ordinal in event names like '1st Service' -> '1<super>ST</super> SERVICE'.
    Falls back to plain uppercase.
    """
    import re
    match = re.match(r'^(\d+)(st|nd|rd|th)\s+(.+)$', event_name, re.IGNORECASE)
    if match:
        num = match.group(1)
        suffix = match.group(2).upper()
        rest = match.group(3).upper()
        return f"{num}<super><font size=8>{suffix}</font></super> {rest}"
    return event_name.upper()


def export_roster_pdf(roster_data: dict) -> bytes:
    """
    Generate a PDF from a roster dictionary (the same shape returned by
    RosterGenerator.generate()).

    Returns the raw PDF bytes.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.6 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    page_width = A4[0] - 1.5 * inch  # usable width

    # Custom styles
    title_style = ParagraphStyle(
        "RosterTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=14,
        fontName="Helvetica-Bold",
        spaceAfter=6,
    )
    producer_style = ParagraphStyle(
        "ProducerLine",
        parent=styles["Normal"],
        fontSize=11,
        fontName="Helvetica-Bold",
        spaceAfter=2,
        leading=15,
    )
    asst_producer_style = ParagraphStyle(
        "AsstProducerLine",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        spaceAfter=2,
        leading=14,
    )
    event_heading_style = ParagraphStyle(
        "EventHeading",
        parent=styles["Normal"],
        fontSize=11,
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=2,
        leading=14,
    )
    special_role_style = ParagraphStyle(
        "SpecialRole",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        spaceAfter=2,
        leading=14,
    )
    responsibilities_heading = ParagraphStyle(
        "ResponsibilitiesHeading",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        spaceBefore=12,
        spaceAfter=4,
        leading=14,
    )
    bullet_style = ParagraphStyle(
        "BulletItem",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica",
        leftIndent=20,
        leading=13,
    )

    elements = []

    # ---- Title ----
    roster_date = roster_data.get("date", "")
    formatted_date = _format_roster_date(roster_date)
    title = Paragraph(
        f"MEDIA DEPT.  DUTY ROSTER  {formatted_date}",
        title_style,
    )
    elements.append(title)
    elements.append(Spacer(1, 6))

    # ---- Producer / Assistant Producer (plain bold text) ----
    producer_name = roster_data.get("producer", {}).get("name", "")
    asst_name = roster_data.get("assistant_producer", {}).get("name", "")
    if producer_name:
        elements.append(
            Paragraph(f"SERVICE PRODUCER &ndash; {producer_name.upper()}", producer_style)
        )
    if asst_name:
        elements.append(
            Paragraph(f"ASSISTANT PRODUCER  - {asst_name.upper()}", asst_producer_style)
        )
    elements.append(Spacer(1, 10))

    # ---- Event / Service tables ----
    col_name_w = page_width * 0.50
    col_role_w = page_width * 0.50

    for event in roster_data.get("events", []):
        event_name = event.get("event_name", "Service")
        heading_text = _format_event_heading(event_name)
        elements.append(Paragraph(heading_text, event_heading_style))

        # Table: NAME | AREA OF SERVICE
        table_rows = [
            [
                Paragraph("<b>NAME</b>", styles["Normal"]),
                Paragraph("<b>AREA OF SERVICE</b>", styles["Normal"]),
            ]
        ]
        for assignment in event.get("assignments", []):
            table_rows.append([
                assignment.get("name", ""),
                assignment.get("role", ""),
            ])

        event_table = Table(table_rows, colWidths=[col_name_w, col_role_w])
        event_table.setStyle(TableStyle([
            # Header row
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            # Body rows
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            # Grid — thin lines
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            # Vertical alignment
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(event_table)
        elements.append(Spacer(1, 6))

    # ---- Special Roles (inline bold text with & separator) ----
    special_roles = roster_data.get("special_roles", {})
    if special_roles:
        elements.append(Spacer(1, 4))
    for role_name, people in special_roles.items():
        if not people:
            continue
        names = []
        for entry in people:
            if isinstance(entry, dict):
                names.append(entry.get("name", ""))
            else:
                names.append(str(entry))
        joined = " &amp; ".join(names) if names else ""
        display_name = role_name.title()
        elements.append(
            Paragraph(f"<b>{display_name}:</b> {joined}", special_role_style)
        )

    # ---- Producer Responsibilities ----
    responsibilities = [
        "To coordinate with the service workers to make sure everything is in order.",
        "To ensure proper and smooth running of all services, in-house and online.",
        "To adhere to the timings of programs.",
        "To make sure photos are taken, edited and posted.",
        "To liaise with the Praise team to ensure the projection of songs and sermons runs smoothly.",
        "To make sure that the overflow hall is ready and everything is set.",
        "To ensure the service workers have everything they need.",
        "To make sure all equipment is set down and put back in their respective places.",
    ]
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>The work of the producer is:</b>", responsibilities_heading))
    bullet_items = []
    for item in responsibilities:
        bullet_items.append(ListItem(Paragraph(item, bullet_style), bulletColor=colors.black))
    elements.append(
        ListFlowable(bullet_items, bulletType='bullet', bulletFontSize=6, leftIndent=18)
    )

    # Build PDF
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
