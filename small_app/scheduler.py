import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import date, datetime, timedelta
from django.db.models import QuerySet, Count, Q
from django.db import transaction
from .models import Persons, Roles, Events, Assignment, Rosters


@dataclass
class RoleAssignment:
    """Data class to represent a role assignment."""
    role: str
    name: str
    person_id: int


class RosterGenerator:
    """Fully dynamic roster generator — all roles and events come from the database."""

    COOLDOWN_GENERATIONS = 3  # Generations a person must sit out before repeating a role

    def __init__(self):
        self.global_assigned: Set[int] = set()
        self.assignment_history: Dict[int, Dict[str, int]] = {}
        self.role_assignment_counts: Dict[str, Dict[int, int]] = {}
        self.generation_cooldown: Dict[int, Set[str]] = {}
        self._assistant_producer_id: Optional[int] = None

    # ------------------------------------------------------------------
    # History & cooldown helpers (unchanged)
    # ------------------------------------------------------------------

    def _load_assignment_history(self, target_date: date, lookback_days: int = 90) -> None:
        """Load assignment history from the last N days to inform rotation decisions."""
        start_date = target_date - timedelta(days=lookback_days)

        recent_assignments = Assignment.objects.filter(
            roster__date__gte=start_date,
            roster__date__lt=target_date
        ).select_related('person', 'role', 'roster__event')

        self.assignment_history.clear()
        self.role_assignment_counts.clear()

        for assignment in recent_assignments:
            person_id = assignment.person.pk
            role_name = assignment.role.name.lower()

            if person_id not in self.assignment_history:
                self.assignment_history[person_id] = {}
            if role_name not in self.assignment_history[person_id]:
                self.assignment_history[person_id][role_name] = 0
            self.assignment_history[person_id][role_name] += 1

            if role_name not in self.role_assignment_counts:
                self.role_assignment_counts[role_name] = {}
            if person_id not in self.role_assignment_counts[role_name]:
                self.role_assignment_counts[role_name][person_id] = 0
            self.role_assignment_counts[role_name][person_id] += 1

        self._load_generation_cooldowns(target_date)

    def _load_generation_cooldowns(self, target_date: date) -> None:
        """Build a hard cooldown map from the last COOLDOWN_GENERATIONS roster dates."""
        self.generation_cooldown.clear()

        recent_dates = list(
            Rosters.objects
            .filter(date__lt=target_date)
            .values_list('date', flat=True)
            .distinct()
            .order_by('-date')[:self.COOLDOWN_GENERATIONS]
        )

        if not recent_dates:
            return

        cooldown_assignments = Assignment.objects.filter(
            roster__date__in=recent_dates
        ).select_related('person', 'role')

        for assignment in cooldown_assignments:
            person_id = assignment.person.pk
            role_name = assignment.role.name.lower()
            if person_id not in self.generation_cooldown:
                self.generation_cooldown[person_id] = set()
            self.generation_cooldown[person_id].add(role_name)

    def _is_on_cooldown(self, person_id: int, role_name: str) -> bool:
        return role_name.lower() in self.generation_cooldown.get(person_id, set())

    def _filter_cooldown(self, people: List[Persons], role_name: str) -> List[Persons]:
        """Remove people on cooldown; fall back to full list when everyone is blocked."""
        available = [p for p in people if not self._is_on_cooldown(p.pk, role_name)]
        return available if available else people

    # ------------------------------------------------------------------
    # Scoring & selection helpers (unchanged)
    # ------------------------------------------------------------------

    def _calculate_person_priority_score(self, person: Persons, role_name: str) -> float:
        person_id = person.pk
        role_lower = role_name.lower()
        score = 0.0

        if role_lower in self.role_assignment_counts:
            recent_role_assignments = self.role_assignment_counts[role_lower].get(person_id, 0)
            score += recent_role_assignments * 10

        total_recent_assignments = sum(self.assignment_history.get(person_id, {}).values())
        score += total_recent_assignments * 2

        score += random.random() * 0.5
        return score

    def _select_best_person_for_role(self, eligible_people: List[Persons], role_name: str) -> Optional[Persons]:
        if not eligible_people:
            return None
        scored_people = [
            (self._calculate_person_priority_score(person, role_name), person)
            for person in eligible_people
        ]
        scored_people.sort(key=lambda x: x[0])
        return scored_people[0][1]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_initial_data(self, events: QuerySet, roles: List[Roles], available_people: QuerySet) -> None:
        if not events.exists():
            raise ValueError("No events defined.")
        if not roles:
            raise ValueError("No roles defined.")
        if not available_people.filter(is_active=True).exists():
            raise ValueError("No people marked as present for the selected date.")

    # ------------------------------------------------------------------
    # Leadership selection (unchanged)
    # ------------------------------------------------------------------

    def _select_producer(self, available_people: QuerySet) -> Persons:
        producer_pool = list(available_people.filter(is_producer=True, is_active=True))
        if not producer_pool:
            raise ValueError("No producer available.")
        candidates = self._filter_cooldown(producer_pool, "producer")
        producer = self._select_best_person_for_role(candidates, "producer")
        if not producer:
            producer = random.choice(candidates)
        self.global_assigned.add(producer.pk)
        return producer

    def _select_assistant_producer(self, available_people: QuerySet) -> Persons:
        assistant_pool = list(
            available_people.filter(is_assistant_producer=True, is_active=True)
            .exclude(pk__in=self.global_assigned)
        )
        if not assistant_pool:
            raise ValueError("No assistant producer available.")
        candidates = self._filter_cooldown(assistant_pool, "assistant producer")
        assistant = self._select_best_person_for_role(candidates, "assistant producer")
        if not assistant:
            assistant = random.choice(candidates)
        # NOTE: Assistant producer is intentionally NOT added to global_assigned
        # so they remain eligible for one additional event/special role.
        self._assistant_producer_id = assistant.pk
        return assistant

    # ------------------------------------------------------------------
    # Dynamic role assignment
    # ------------------------------------------------------------------

    def _assign_event_roles(self, event: Events, available_people: QuerySet, roles: List[Roles]) -> List[RoleAssignment]:
        """Assign every non-special role for a single event."""
        event_assignments = []
        non_special_roles = [r for r in roles if not r.is_special_role]

        for role in non_special_roles:
            role_name = role.name

            # People who are configured for this role
            capable = [
                p for p in available_people
                if role in p.roles.all()
            ]
            if not capable:
                # Nobody is configured for this role — skip silently
                # (avoids noise for auto-created leadership roles like "Producer")
                continue

            not_yet_assigned = [p for p in capable if p.pk not in self.global_assigned]
            eligible = self._filter_cooldown(not_yet_assigned, role_name)

            if eligible:
                chosen = self._select_best_person_for_role(eligible, role_name)
                if not chosen:
                    chosen = random.choice(eligible)
                event_assignments.append(RoleAssignment(
                    role=role_name,
                    name=f"{chosen.first_name} {chosen.last_name}",
                    person_id=chosen.pk,
                ))
                self.global_assigned.add(chosen.pk)
                # If the assistant producer just got their one extra role, lock them out
                if chosen.pk == self._assistant_producer_id:
                    self.global_assigned.add(chosen.pk)
            else:
                print(f"Warning: No available people for role '{role_name}' in event '{event.description}'")

        return event_assignments

    def _assign_special_roles(self, available_people: QuerySet, roles: List[Roles]) -> Dict[str, List[Dict]]:
        """Assign every special role dynamically from the database."""
        result: Dict[str, List[Dict]] = {}
        special_roles = [r for r in roles if r.is_special_role]

        for role in special_roles:
            role_name = role.name
            max_count = role.max_assignments

            capable = [
                p for p in available_people
                if role in p.roles.all()
            ]
            if not capable:
                continue

            not_yet_assigned = [p for p in capable if p.pk not in self.global_assigned]
            candidates = self._filter_cooldown(not_yet_assigned, role_name)

            if not candidates:
                print(f"Warning: No one available for special role '{role_name}'")
                result[role_name.lower()] = []
                continue

            selected = []
            remaining = list(candidates)
            for _ in range(min(max_count, len(remaining))):
                best = self._select_best_person_for_role(remaining, role_name)
                if best:
                    selected.append(best)
                    remaining.remove(best)

            if not selected and candidates:
                selected = random.sample(candidates, min(max_count, len(candidates)))

            result[role_name.lower()] = [
                {"person_id": p.pk, "name": f"{p.first_name} {p.last_name}"}
                for p in selected
            ]
            self.global_assigned.update(p.pk for p in selected)

        return result

    # ------------------------------------------------------------------
    # Main generation
    # ------------------------------------------------------------------

    def generate(self, target_date: date) -> Dict:
        """Generate a roster for the given date — fully driven by database roles."""
        print(f"Starting roster generation for date: {target_date}")

        self.global_assigned.clear()
        self._load_assignment_history(target_date)

        events = Events.objects.filter(is_active=True).order_by('id')
        roles = list(Roles.objects.all())
        available_people = Persons.objects.filter(
            is_present=True, is_active=True
        ).prefetch_related('roles')

        self._validate_initial_data(events, roles, available_people)

        # Leadership
        producer = self._select_producer(available_people)
        assistant_producer = self._select_assistant_producer(available_people)

        # Event roles
        event_list = []
        for event in events:
            assignments = self._assign_event_roles(event, available_people, roles)
            event_list.append({
                "event_id": event.pk,
                "event_name": event.description or event.name or "Unknown Event",
                "assignments": [
                    {"role": a.role, "name": a.name, "person_id": a.person_id}
                    for a in assignments
                ],
            })

        # Special roles (fully dynamic)
        special_roles = self._assign_special_roles(available_people, roles)

        print(f"Roster generated successfully. Total assigned: {len(self.global_assigned)}")

        # Summary
        all_people = list(available_people)
        assigned_list = [
            {"person_id": p.pk, "name": f"{p.first_name} {p.last_name}"}
            for p in all_people if p.pk in self.global_assigned
        ]
        not_assigned_list = [
            {"person_id": p.pk, "name": f"{p.first_name} {p.last_name}"}
            for p in all_people if p.pk not in self.global_assigned
        ]

        return {
            "date": str(target_date),
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_people_available": len(all_people),
                "total_assignments": len(self.global_assigned),
            },
            "producer": {
                "id": producer.pk,
                "name": f"{producer.first_name} {producer.last_name}",
            },
            "assistant_producer": {
                "id": assistant_producer.pk,
                "name": f"{assistant_producer.first_name} {assistant_producer.last_name}",
            },
            "events": event_list,
            "special_roles": special_roles,
            "summary": {
                "people_assigned": assigned_list,
                "people_not_assigned": not_assigned_list,
            },
        }

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    def save_roster_to_database(self, roster_data: Dict, target_date: date) -> None:
        """Save the generated roster to the database for tracking assignment history."""
        try:
            with transaction.atomic():
                events = Events.objects.filter(is_active=True)
                first_roster_entry = None

                for event in events:
                    event_data = next(
                        (s for s in roster_data.get('events', []) if s['event_id'] == event.pk),
                        None,
                    )
                    if not event_data:
                        continue

                    roster_entry, _ = Rosters.objects.get_or_create(
                        event=event,
                        date=target_date,
                    )

                    if first_roster_entry is None:
                        first_roster_entry = roster_entry

                    # Clear existing assignments for this roster entry
                    Assignment.objects.filter(roster=roster_entry).delete()

                    for assignment_data in event_data.get('assignments', []):
                        try:
                            person = Persons.objects.get(id=assignment_data['person_id'])
                            role = Roles.objects.filter(name__iexact=assignment_data['role']).first()
                            if role:
                                Assignment.objects.create(
                                    roster=roster_entry,
                                    role=role,
                                    person=person,
                                )
                        except Persons.DoesNotExist as e:
                            print(f"Warning: Could not create assignment - {e}")

                # Leadership + special roles saved to the first roster entry
                if first_roster_entry:
                    self._save_leadership_assignments(roster_data, first_roster_entry)
                    self._save_special_role_assignments(roster_data, first_roster_entry)

                print(f"Roster saved to database for {target_date}")

        except Exception as e:
            print(f"Error saving roster to database: {e}")
            raise

    def _save_leadership_assignments(self, roster_data: Dict, roster_entry: Rosters) -> None:
        """Save producer and assistant producer assignments."""
        leadership = [
            ("producer", "Producer"),
            ("assistant_producer", "Assistant Producer"),
        ]
        for data_key, role_display_name in leadership:
            person_data = roster_data.get(data_key)
            if not person_data:
                continue
            try:
                person = Persons.objects.get(id=person_data['id'])
            except Persons.DoesNotExist:
                print(f"Warning: Person not found for {role_display_name} assignment")
                continue
            role, _ = Roles.objects.get_or_create(
                name=role_display_name,
                defaults={"description": role_display_name, "is_special_role": False},
            )
            Assignment.objects.get_or_create(
                roster=roster_entry,
                role=role,
                person=person,
            )

    def _save_special_role_assignments(self, roster_data: Dict, roster_entry: Rosters) -> None:
        """Save special role assignments for cooldown tracking."""
        special_roles = roster_data.get('special_roles', {})
        for role_key, people in special_roles.items():
            role = Roles.objects.filter(name__iexact=role_key).first()
            if not role:
                continue
            for person_data in people:
                try:
                    person = Persons.objects.get(id=person_data['person_id'])
                    Assignment.objects.get_or_create(
                        roster=roster_entry,
                        role=role,
                        person=person,
                    )
                except Persons.DoesNotExist:
                    print(f"Warning: Person {person_data.get('person_id')} not found for '{role_key}'")


def generate_roster(target_date: date, save_to_db: bool = True) -> Dict:
    """Generate roster with effective rotation and automatic saving."""
    generator = RosterGenerator()
    roster_data = generator.generate(target_date)

    if save_to_db:
        try:
            generator.save_roster_to_database(roster_data, target_date)
            print("Roster automatically saved to database for rotation tracking")
        except Exception as e:
            print(f"Warning: Could not save roster to database: {e}")

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
