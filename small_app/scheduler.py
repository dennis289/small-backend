import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import date, timedelta
from django.db.models import QuerySet, Count, Q
from django.db import transaction
from .models import Persons, Roles, Events, Assignment, Rosters


@dataclass
class PersonInfo:
    """Data class to represent a person's basic information."""
    id: int
    name: str
    first_name: str
    last_name: str


@dataclass
class RoleAssignment:
    """Data class to represent a role assignment."""
    role: str
    name: str
    person_id: int


@dataclass
class EventAssignment:
    """Data class to represent assignments for an event."""
    event_id: int
    event_name: str
    assignments: List[RoleAssignment] = field(default_factory=list)


@dataclass
class RosterStructure:
    """Data class to represent the complete roster structure."""
    date: str
    producer: PersonInfo
    assistant_producer: PersonInfo
    events: List[EventAssignment] = field(default_factory=list)
    hospitality: List[str] = field(default_factory=list)
    social_media: List[str] = field(default_factory=list)


class RosterGenerator:
    """Modern roster generator class with effective rotation system."""
    
    ROLE_LABELS = [
        ("Camera 1", "Videography"),
        ("Camera 2", "Videography"),
        ("Projecting", "Projecting"),
        ("Streaming", "Streaming"),
        ("Still Images", "Photography"),
        ("Media Desk", "Media Desk"),
        ("Time Keeper", "Time keeper")
    ]
    
    def __init__(self):
        self.global_assigned: Set[int] = set()
        self.assignment_history: Dict[int, Dict[str, int]] = {}
        self.role_assignment_counts: Dict[str, Dict[int, int]] = {}
    
    def _load_assignment_history(self, target_date: date, lookback_days: int = 90) -> None:
        """Load assignment history from the last N days to inform rotation decisions."""
        start_date = target_date - timedelta(days=lookback_days)
        
        # Get all assignments from the lookback period
        recent_assignments = Assignment.objects.filter(
            roster__date__gte=start_date,
            roster__date__lt=target_date
        ).select_related('person', 'role', 'roster__event')
        
        # Reset history tracking
        self.assignment_history.clear()
        self.role_assignment_counts.clear()
        
        # Build assignment history
        for assignment in recent_assignments:
            person_id = assignment.person.pk
            role_name = assignment.role.name.lower()
            
            # Track general assignment history per person
            if person_id not in self.assignment_history:
                self.assignment_history[person_id] = {}
            
            if role_name not in self.assignment_history[person_id]:
                self.assignment_history[person_id][role_name] = 0
            
            self.assignment_history[person_id][role_name] += 1
            
            # Track role assignment counts for rotation
            if role_name not in self.role_assignment_counts:
                self.role_assignment_counts[role_name] = {}
            
            if person_id not in self.role_assignment_counts[role_name]:
                self.role_assignment_counts[role_name][person_id] = 0
            
            self.role_assignment_counts[role_name][person_id] += 1
        
    
    def _calculate_person_priority_score(self, person: Persons, role_name: str) -> float:
        """
        Calculate a priority score for assigning a person to a role.
        Lower score = higher priority (should be assigned first).
        """
        person_id = person.pk
        role_lower = role_name.lower()
        
        # Base score
        score = 0.0
        
        # Factor 1: Recent assignment frequency for this specific role (heavily weighted)
        if role_lower in self.role_assignment_counts:
            recent_role_assignments = self.role_assignment_counts[role_lower].get(person_id, 0)
            score += recent_role_assignments * 10  # Heavy penalty for recent same-role assignments
        
        # Factor 2: Total assignment frequency across all roles (moderate weight)
        total_recent_assignments = sum(self.assignment_history.get(person_id, {}).values())
        score += total_recent_assignments * 2  # Moderate penalty for being assigned frequently
        
        # Factor 3: Random factor for tie-breaking (small weight)
        score += random.random() * 0.5
        
        return score
    
    def _select_best_person_for_role(self, eligible_people: List[Persons], role_name: str) -> Optional[Persons]:
        """Select the best person for a role based on rotation history."""
        if not eligible_people:
            return None
        
        # Calculate priority scores for all eligible people
        scored_people = [
            (self._calculate_person_priority_score(person, role_name), person)
            for person in eligible_people
        ]
        
        # Sort by score (ascending - lowest score = highest priority)
        scored_people.sort(key=lambda x: x[0])
        
        # Select the person with the lowest score (highest priority)
        selected_person = scored_people[0][1]
        
        # print(f"Selected {selected_person.first_name} {selected_person.last_name} for {role_name} "
        #       f"(priority score: {scored_people[0][0]:.2f})")
        
        return selected_person
    
    def _get_person_info(self, person: Persons) -> PersonInfo:
        """Convert a Persons model instance to PersonInfo dataclass."""
        return PersonInfo(
            id=person.pk,
            name=f"{person.first_name} {person.last_name}",
            first_name=person.first_name,
            last_name=person.last_name
        )
    
    def _validate_initial_data(self, events: QuerySet, roles: List[Roles], available_people: QuerySet) -> None:
        """Validate that required data exists before roster generation."""
        if not events.exists():
            raise ValueError("No events defined.")
        if not roles:
            raise ValueError("No roles defined.")
        if not available_people.exists():
            raise ValueError("No people marked as present for the selected date.")
    
    def _select_producer(self, available_people: QuerySet) -> Persons:
        """Select a producer from available people using rotation logic."""
        producer_pool = available_people.filter(is_producer=True)
        if not producer_pool.exists():
            raise ValueError("No producer available.")
        
        # Use rotation logic for producer selection
        producer = self._select_best_person_for_role(list(producer_pool), "producer")
        if not producer:
            # Fallback to random if rotation logic fails
            producer = random.choice(list(producer_pool))
        
        self.global_assigned.add(producer.pk)
        return producer
    
    def _select_assistant_producer(self, available_people: QuerySet) -> Persons:
        """Select an assistant producer using rotation logic (excluding already assigned)."""
        eligible_assistants = available_people.filter(is_assistant_producer=True).exclude(pk__in=self.global_assigned)
        if not eligible_assistants.exists():
            raise ValueError("No assistant producer available.")
        
        # Use rotation logic for assistant producer selection
        assistant_producer = self._select_best_person_for_role(list(eligible_assistants), "assistant_producer")
        if not assistant_producer:
            # Fallback to random if rotation logic fails
            assistant_producer = random.choice(list(eligible_assistants))
        
        self.global_assigned.add(assistant_producer.pk)
        return assistant_producer
    
    def _assign_event_roles(self, event: Events, available_people: QuerySet, roles: List[Roles]) -> List[RoleAssignment]:
        """Assign roles for a specific event using effective rotation logic."""
        event_assignments = []
        
        for display_name, db_role_name in self.ROLE_LABELS:
            db_role = next((r for r in roles if r.name.lower() == db_role_name.lower()), None)
            if not db_role:
                print(f"Warning: Role '{db_role_name}' not found in database")
                continue
            
            eligible = [
                p for p in available_people
                if db_role in p.roles.all() and p.pk not in self.global_assigned
            ]
            
            if eligible:
                # Use rotation-based selection instead of random
                chosen = self._select_best_person_for_role(eligible, db_role_name)
                if not chosen:
                    # Fallback to random if rotation logic fails
                    chosen = random.choice(eligible)
                
                event_assignments.append(RoleAssignment(
                    role=display_name,
                    name=f"{chosen.first_name} {chosen.last_name}",
                    person_id=chosen.pk
                ))
                self.global_assigned.add(chosen.pk)
            else:
                print(f"Warning: No available people for role '{display_name}' in event '{event.description}'")
        
        return event_assignments
    
    def _assign_hospitality(self, available_people: QuerySet, hospitality_role: Optional[Roles]) -> List[str]:
        """Assign hospitality roles using rotation logic."""
        if not hospitality_role:
            print("Warning: Hospitality role not found")
            return []
        
        hospitality_candidates = [
            p for p in available_people
            if hospitality_role in p.roles.all() and p.pk not in self.global_assigned
        ]
        
        if not hospitality_candidates:
            print("Warning: No one available for Hospitality role")
            return []
        
        # Select up to 2 people using rotation logic
        selected = []
        for i in range(min(2, len(hospitality_candidates))):
            best_person = self._select_best_person_for_role(hospitality_candidates, "hospitality")
            if best_person:
                selected.append(best_person)
                hospitality_candidates.remove(best_person)  # Remove from candidates for next selection
        
        # Fallback to random selection if rotation logic didn't work
        if not selected:
            selected = random.sample(hospitality_candidates, min(2, len(hospitality_candidates)))
        
        hospitality_names = [f"{p.first_name} {p.last_name}" for p in selected]
        self.global_assigned.update(p.pk for p in selected)
        
        return hospitality_names
    
    def _assign_social_media(self, available_people: QuerySet, social_media_role: Optional[Roles]) -> List[str]:
        """Assign social media role using rotation logic, with Victor Reuben preference."""
        if not social_media_role:
            print("Warning: Social Media role not found")
            return []
        
        # Try to assign Victor Reuben first (maintaining existing preference)
        victor = available_people.filter(
            first_name__iexact="Victor", 
            last_name__iexact="Reuben"
        ).first()
        
        if victor and social_media_role in victor.roles.all() and victor.pk not in self.global_assigned:
            # Check if Victor has been assigned to social media recently
            victor_score = self._calculate_person_priority_score(victor, "social media")
            
            # If Victor hasn't been assigned recently (score < 5), assign him
            if victor_score < 5.0:
                self.global_assigned.add(victor.pk)
                return [f"{victor.first_name} {victor.last_name}"]
            else:
                print(f"Victor Reuben recently assigned to social media (score: {victor_score:.2f}), using rotation")
        
        # Use rotation logic for social media assignment
        social_media_candidates = [
            p for p in available_people
            if social_media_role in p.roles.all() and p.pk not in self.global_assigned
        ]
        
        if social_media_candidates:
            chosen = self._select_best_person_for_role(social_media_candidates, "social media")
            if not chosen:
                # Fallback to random if rotation logic fails
                chosen = random.choice(social_media_candidates)
            
            self.global_assigned.add(chosen.pk)
            return [f"{chosen.first_name} {chosen.last_name}"]
        
        print("Warning: No one available for Social Media role")
        return []
    
    def generate(self, target_date: date) -> Dict:
        """Generate a roster for the given date with effective rotation system."""
        print(f"Starting roster generation for date: {target_date}")
        
        # Reset global assignments for this generation
        self.global_assigned.clear()
        
        # Load assignment history for rotation logic
        self._load_assignment_history(target_date)
        
        # Fetch data
        events = Events.objects.filter(is_active=True).order_by('id')
        roles = list(Roles.objects.all())
        available_people = Persons.objects.filter(is_present=True).prefetch_related('roles')
        
        # Validate initial data
        self._validate_initial_data(events, roles, available_people)
        
        # Select producer and assistant producer using rotation
        producer = self._select_producer(available_people)
        assistant_producer = self._select_assistant_producer(available_people)
        
        # Find special roles
        hospitality_role = next((r for r in roles if r.name.lower() == "hospitality"), None)
        social_media_role = next((r for r in roles if r.name.lower() == "social media"), None)
        
        # Initialize roster structure
        roster = RosterStructure(
            date=str(target_date),
            producer=self._get_person_info(producer),
            assistant_producer=self._get_person_info(assistant_producer)
        )
        
        # Assign roles for each event using rotation
        for event in events:
            event_assignments = self._assign_event_roles(event, available_people, roles)
            roster.events.append(EventAssignment(
                event_id=event.pk,
                event_name=event.description or "Unknown Event",
                assignments=event_assignments
            ))
        
        # Assign special roles using rotation
        roster.hospitality = self._assign_hospitality(available_people, hospitality_role)
        roster.social_media = self._assign_social_media(available_people, social_media_role)
        
        print(f"Roster generated successfully with rotation logic. Total people assigned: {len(self.global_assigned)}")
        
        # Convert to dictionary for backward compatibility
        return {
            "date": roster.date,
            "producer": {
                "id": roster.producer.id,
                "name": roster.producer.name
            },
            "assistant_producer": {
                "id": roster.assistant_producer.id,
                "name": roster.assistant_producer.name
            },
            "events": [
                {
                    "event_id": event.event_id,
                    "event_name": event.event_name,
                    "assignments": [
                        {
                            "role": assignment.role,
                            "name": assignment.name,
                            "person_id": assignment.person_id
                        }
                        for assignment in event.assignments
                    ]
                }
                for event in roster.events
            ],
            "hospitality": roster.hospitality,
            "social_media": roster.social_media
        }
    
    def save_roster_to_database(self, roster_data: Dict, target_date: date) -> None:
        """Save the generated roster to the database for tracking assignment history."""
        try:
            with transaction.atomic():
                # Create roster entries for each event
                events = Events.objects.filter(is_active=True)
                
                for event in events:
                    # Find corresponding event assignments in roster data
                    event_data = next(
                        (s for s in roster_data.get('events', []) if s['event_id'] == event.pk),
                        None
                    )
                    
                    if not event_data:
                        continue
                    
                    # Create or update roster entry
                    roster_entry, created = Rosters.objects.get_or_create(
                        event=event,
                        date=target_date,
                        defaults={'person_id': 1}  # Placeholder person
                    )
                    
                    # Clear existing assignments for this roster entry
                    Assignment.objects.filter(roster=roster_entry).delete()
                    
                    # Create new assignments
                    for assignment_data in event_data.get('assignments', []):
                        try:
                            person = Persons.objects.get(id=assignment_data['person_id'])
                            role_name = assignment_data['role']
                            
                            # Map display name to database role name
                            db_role_name = next(
                                (db_name for display_name, db_name in self.ROLE_LABELS if display_name == role_name),
                                role_name
                            )
                            
                            role = Roles.objects.filter(name__iexact=db_role_name).first()
                            if role:
                                Assignment.objects.create(
                                    roster=roster_entry,
                                    role=role,
                                    person=person
                                )
                        except (Persons.DoesNotExist, Roles.DoesNotExist) as e:
                            print(f"Warning: Could not create assignment - {e}")
                
                print(f"Roster saved to database for {target_date}")
                
        except Exception as e:
            print(f"Error saving roster to database: {e}")
            raise


def generate_roster(target_date: date, save_to_db: bool = True) -> Dict:
    """
    Generate roster with effective rotation and automatic saving.
    Uses the new RosterGenerator class with rotation logic.
    
    Args:
        target_date: The date to generate the roster for
        save_to_db: Whether to automatically save the roster to database for tracking (default: True)
    
    Returns:
        Dictionary containing the generated roster data
    """
    generator = RosterGenerator()
    roster_data = generator.generate(target_date)
    
    # Automatically save to database for rotation tracking
    if save_to_db:
        try:
            generator.save_roster_to_database(roster_data, target_date)
            print("Roster automatically saved to database for rotation tracking")
        except Exception as e:
            print(f"Warning: Could not save roster to database: {e}")
            # Continue execution even if saving fails
    
    return roster_data


def get_assignment_statistics(lookback_days: int = 90) -> Dict:
    """
    Get assignment statistics for the last N days to help with roster planning.
    
    Args:
        lookback_days: Number of days to look back for statistics
    
    Returns:
        Dictionary containing assignment statistics
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    
    # Get all assignments in the period
    assignments = Assignment.objects.filter(
        roster__date__gte=start_date,
        roster__date__lte=end_date
    ).select_related('person', 'role')
    
    # Calculate statistics
    person_stats = {}
    role_stats = {}
    
    for assignment in assignments:
        person_name = f"{assignment.person.first_name} {assignment.person.last_name}"
        role_name = assignment.role.name
        
        # Person statistics
        if person_name not in person_stats:
            person_stats[person_name] = {"total_assignments": 0, "roles": {}}
        
        person_stats[person_name]["total_assignments"] += 1
        
        if role_name not in person_stats[person_name]["roles"]:
            person_stats[person_name]["roles"][role_name] = 0
        person_stats[person_name]["roles"][role_name] += 1
        
        # Role statistics
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
        "total_assignments": len(assignments)
    }
