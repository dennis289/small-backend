#!/usr/bin/env python3
"""
Test script for the optimized scheduler that minimizes double assignments.
"""

import os
import sys
import django
from datetime import date, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'small_backend.settings')
django.setup()

from small_app.scheduler import generate_roster
from small_app.models import Persons, Roles, Services

def test_optimized_scheduler():
    """Test the optimized scheduler functionality."""
    
    print("=" * 60)
    print("TESTING OPTIMIZED SCHEDULER - MINIMAL DOUBLE ASSIGNMENTS")
    print("=" * 60)
    
    # Test date
    test_date = date.today() + timedelta(days=3)
    
    # Check current data
    print(f"\nCurrent data status:")
    print(f"- People available: {Persons.objects.filter(is_present=True).count()}")
    print(f"- Total roles: {Roles.objects.count()}")
    print(f"- Active services: {Services.objects.filter(is_active=True).count()}")
    
    # Generate roster
    print(f"\nGenerating optimized roster for {test_date}...")
    print("-" * 50)
    
    try:
        roster_data = generate_roster(test_date, save_to_db=False)
        
        print("-" * 50)
        print(f"Optimized Roster Generation Completed!")
        
        # Analyze the results for double assignments
        person_assignment_count = {}
        
        # Count producer and assistant producer
        producer_id = roster_data['producer']['id']
        assistant_producer_id = roster_data['assistant_producer']['id']
        
        person_assignment_count[producer_id] = 1
        person_assignment_count[assistant_producer_id] = 1
        
        # Count service assignments
        total_service_assignments = 0
        for service in roster_data['services']:
            total_service_assignments += len(service['assignments'])
            for assignment in service['assignments']:
                person_id = assignment['person_id']
                person_assignment_count[person_id] = person_assignment_count.get(person_id, 0) + 1
        
        # Count hospitality and social media (simplified - assuming names map to people)
        # In real implementation, we'd need to map names back to person IDs
        
        # Calculate double assignment metrics
        people_with_multiple = [
            (person_id, count) for person_id, count in person_assignment_count.items() 
            if count > 1
        ]
        
        total_people_assigned = len(person_assignment_count)
        total_assignments = sum(person_assignment_count.values())
        double_assignment_rate = (len(people_with_multiple) / total_people_assigned) * 100 if total_people_assigned > 0 else 0
        avg_assignments = total_assignments / total_people_assigned if total_people_assigned > 0 else 0
        
        print(f"\n📊 OPTIMIZATION RESULTS:")
        print(f"- Total people assigned: {total_people_assigned}")
        print(f"- Total assignments: {total_assignments}")
        print(f"- Average assignments per person: {avg_assignments:.2f}")
        print(f"- People with multiple assignments: {len(people_with_multiple)}")
        print(f"- Double assignment rate: {double_assignment_rate:.1f}%")
        
        if double_assignment_rate < 30:
            print("✅ OPTIMIZATION SUCCESS: Double assignment rate < 30%")
        else:
            print("⚠️  OPTIMIZATION NEEDS IMPROVEMENT: High double assignment rate")
        
        if people_with_multiple:
            print(f"\nPeople with multiple assignments:")
            for person_id, count in people_with_multiple:
                # Find person name (simplified lookup)
                try:
                    person = Persons.objects.get(id=person_id)
                    print(f"  - {person.first_name} {person.last_name}: {count} assignments")
                except Persons.DoesNotExist:
                    print(f"  - Person ID {person_id}: {count} assignments")
        
        # Show detailed roster
        print(f"\n📋 DETAILED ROSTER:")
        print(f"- Producer: {roster_data['producer']['name']}")
        print(f"- Assistant Producer: {roster_data['assistant_producer']['name']}")
        
        for service in roster_data['services']:
            print(f"\n  {service['service_name']}:")
            for assignment in service['assignments']:
                print(f"    - {assignment['role']}: {assignment['name']}")
        
        if roster_data['hospitality']:
            print(f"\n  Hospitality: {', '.join(roster_data['hospitality'])}")
        
        if roster_data['social_media']:
            print(f"  Social Media: {', '.join(roster_data['social_media'])}")
        
    except Exception as e:
        print(f"Error generating roster: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("OPTIMIZATION TEST COMPLETED")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    test_optimized_scheduler()
