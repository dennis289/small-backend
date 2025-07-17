import random
from .models import *
from datetime import date

def generate_roster(target_date: date):
    print(f"Starting roster generation for date: {target_date}")
    
    services = list(Services.objects.filter(is_active=True).order_by('id'))
    roles = list(Roles.objects.all())
    if not services:
        raise ValueError("No services defined.")
    if not roles:
        raise ValueError("No roles defined.")
    
    # Use Persons directly
    available_people = Persons.objects.filter(is_present=True).prefetch_related('roles')

    if not available_people.exists():
        raise ValueError("No people marked as present for the selected date.")

    # Randomized producer from available producers
    producer_pool = available_people.filter(is_producer=True)
    producer = random.choice(list(producer_pool)) if producer_pool.exists() else None
    if not producer:
        raise ValueError("No producer available.")
    
    eligible_assistants = available_people.exclude(id=producer.id)
    assistant_producer = random.choice(list(eligible_assistants)) if eligible_assistants.exists() else None
    if not assistant_producer:
        raise ValueError("No assistant producer available.")
    
    # Fetch special roles
    hospitality_role = next((r for r in roles if r.name.lower() == "hospitality"), None)
    social_media_role = next((r for r in roles if r.name.lower() == "social media"), None)

    ROLE_LABELS = [
        ("Camera 1", "Videography"),
        ("Camera 2", "Videography"),
        ("Projecting", "Projecting"),
        ("Streaming", "Streaming"),
        ("Still Images", "Photography"),
        ("Media Desk", "Media Desk"),
        ("Time Keeper", "Time keeper")
    ]

    structured = {
        "date": str(target_date),
        "producer": {
            "id": producer.id,
            "name": f"{producer.first_name} {producer.last_name}"
        },
        "assistant_producer": {
            "id": assistant_producer.id,
            "name": f"{assistant_producer.first_name} {assistant_producer.last_name}"
        },
        "services": [],
        "hospitality": [],
        "social_media": []
    }

    global_assigned = set([producer.id, assistant_producer.id])

    for service in services:
        service_assignments = []
        local_assigned = set(global_assigned)

        for display_name, db_role_name in ROLE_LABELS:
            db_role = next((r for r in roles if r.name.lower() == db_role_name.lower()), None)
            if not db_role:
                continue

            eligible = [
                p for p in available_people
                if db_role in p.roles.all() and p.id not in local_assigned
            ]

            if not eligible:
                eligible = [
                    p for p in available_people
                    if db_role in p.roles.all()
                ]

            if eligible:
                random.shuffle(eligible)
                chosen = eligible[0]
                service_assignments.append({
                    "role": display_name,
                    "name": f"{chosen.first_name} {chosen.last_name}"
                })
                local_assigned.add(chosen.id)
                global_assigned.add(chosen.id)

        structured["services"].append({
            "service_id": service.id,
            "service_name": service.description,
            "assignments": service_assignments
        })

    # Assign 2 Hospitality
    if hospitality_role:
        hospitality_candidates = [
            p for p in available_people
            if hospitality_role in p.roles.all() and p.id not in global_assigned
        ]
        selected = random.sample(hospitality_candidates, min(2, len(hospitality_candidates)))
        structured["hospitality"] = [f"{p.first_name} {p.last_name}" for p in selected]
        global_assigned.update(p.id for p in selected)

    # Assign Social Media to Victor Reuben
    if social_media_role:
        victor = available_people.filter(first_name__iexact="Victor", last_name__iexact="Reuben").first()
        if victor and social_media_role in victor.roles.all():
            structured["social_media"] = [f"{victor.first_name} {victor.last_name}"]
            global_assigned.add(victor.id)

    print("Roster generated successfully.")
    return structured
