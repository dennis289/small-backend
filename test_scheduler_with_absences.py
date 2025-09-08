#!/usr/bin/env python3
"""
Test script to demonstrate enhanced scheduler with some people marked as absent.
"""

import os
import sys
import django
from datetime import date, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'small_backend.settings')
django.setup()

from small_app.scheduler import generate_roster, get_assignment_statistics, get_role_diversity_analysis
from small_app.models import Persons, Roles, Services

def test_scheduler_with_absences():
    """Test the enhanced scheduler with some people marked as absent."""
    
    print("=" * 60)
    print("TESTING SCHEDULER WITH PEOPLE ABSENT")
    print("=" * 60)
    
    # Mark some people as absent (is_present=False)
    absent_people = Persons.objects.filter(
        first_name__in=["Victor", "Emmanuel", "Grace", "David", "Eliud"]
    )[:3]  # Mark first 3 as absent
    
    original_status = {}
    for person in absent_people:
        original_status[person.id] = person.is_present
        person.is_present = False
        person.save()
        print(f"Marked {person.first_name} {person.last_name} as ABSENT")
    
    try:
        # Test date
        test_date = date.today() + timedelta(days=2)
        
        # Check current data
        total_people = Persons.objects.count()
        available_people = Persons.objects.filter(is_present=True).count()
        absent_count = total_people - available_people
        
        print(f"\nCurrent status:")
        print(f"- Total people: {total_people}")
        print(f"- Available people: {available_people}")
        print(f"- Absent people: {absent_count}")
        print(f"- Active services: {Services.objects.filter(is_active=True).count()}")
        
        # Generate roster
        print(f"\nGenerating roster for {test_date} with absences...")
        print("-" * 50)
        
        roster_data = generate_roster(test_date, save_to_db=False)
        
        print("-" * 50)
        print(f"Roster Generation with Absences Completed!")
        print(f"\nRoster Summary:")
        print(f"- Producer: {roster_data['producer']['name']}")
        print(f"- Assistant Producer: {roster_data['assistant_producer']['name']}")
        print(f"- Services with assignments: {len(roster_data['services'])}")
        print(f"- Hospitality team: {len(roster_data['hospitality'])} people")
        print(f"- Social media: {len(roster_data['social_media'])} people")
        
        # Count total assignments
        total_assignments = 2  # producer + assistant producer
        for service in roster_data['services']:
            total_assignments += len(service['assignments'])
        total_assignments += len(roster_data['hospitality']) + len(roster_data['social_media'])
        
        print(f"- Total role assignments: {total_assignments}")
        
        # Show service assignments
        for service in roster_data['services']:
            print(f"\n  {service['service_name']}:")
            for assignment in service['assignments']:
                print(f"    - {assignment['role']}: {assignment['name']}")
        
        if roster_data['hospitality']:
            print(f"\n  Hospitality: {', '.join(roster_data['hospitality'])}")
        
        if roster_data['social_media']:
            print(f"  Social Media: {', '.join(roster_data['social_media'])}")
            
    finally:
        # Restore original status
        print(f"\nRestoring original attendance status...")
        for person in absent_people:
            person.is_present = original_status[person.id]
            person.save()
            print(f"Restored {person.first_name} {person.last_name} to PRESENT")
    
    print("\n" + "=" * 60)
    print("ABSENCE HANDLING TEST COMPLETED")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    test_scheduler_with_absences()
