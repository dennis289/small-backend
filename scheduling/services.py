from datetime import date, timedelta
from typing import Dict
from small_app.models import Assignment
from .generator import RosterGenerator


def generate_roster(
    target_date: date,
    save_to_db: bool = True,
    client=None,
    inactive_events=None,
    absent_members=None,
) -> Dict:
    """Generate roster with effective rotation and automatic saving.

    ``inactive_events`` and ``absent_members`` are excluded for this generation
    only and do not change the persisted ``is_active`` / ``is_present`` flags.
    """
    generator = RosterGenerator(client=client)
    roster_data = generator.generate(
        target_date,
        inactive_events=inactive_events or [],
        absent_members=absent_members or [],
    )

    # if save_to_db:
    #     try:
    #         generator.save_roster_to_database(roster_data, target_date)
    #         print("Roster automatically saved to database for rotation tracking")
    #     except Exception as e:
    #         print(f"Warning: Could not save roster to database: {e}")

    return roster_data


def get_assignment_statistics(lookback_days: int = 90) -> Dict:
    """Get assignment statistics for the last N days."""
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    assignments = Assignment.objects.filter(
        roster__date__gte=start_date,
        roster__date__lte=end_date
    ).select_related('person', 'role')

    person_stats = {}
    role_stats = {}

    for assignment in assignments:
        person_name = f"{assignment.person.first_name} {assignment.person.last_name}"
        role_name = assignment.role.name

        if person_name not in person_stats:
            person_stats[person_name] = {"total_assignments": 0, "roles": {}}
        person_stats[person_name]["total_assignments"] += 1
        if role_name not in person_stats[person_name]["roles"]:
            person_stats[person_name]["roles"][role_name] = 0
        person_stats[person_name]["roles"][role_name] += 1

        if role_name not in role_stats:
            role_stats[role_name] = {"total_assignments": 0, "people": {}}
        role_stats[role_name]["total_assignments"] += 1
        if person_name not in role_stats[role_name]["people"]:
            role_stats[role_name]["people"][person_name] = 0
        role_stats[role_name]["people"][person_name] += 1

    return {
        "period": f"{start_date} to {end_date}",
        "person_statistics": person_stats,
        "role_statistics": role_stats,
        "total_assignments": len(assignments),
    }
