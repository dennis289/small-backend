#!/usr/bin/env python3
"""
Test script for the enhanced roster scheduler with role diversity optimization.
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

def test_enhanced_scheduler():
    """Test the enhanced scheduler functionality."""
    
    print("=" * 60)
    print("TESTING ENHANCED ROSTER SCHEDULER")
    print("=" * 60)
    
    # Test date
    test_date = date.today() + timedelta(days=1)
    
    # Check current data
    print(f"\nCurrent data status:")
    print(f"- People available: {Persons.objects.filter(is_present=True).count()}")
    print(f"- Total roles: {Roles.objects.count()}")
    print(f"- Active services: {Services.objects.filter(is_active=True).count()}")
    
    # Get diversity analysis before generation
    print(f"\nRole Diversity Analysis (before generation):")
    diversity_analysis = get_role_diversity_analysis(lookback_days=30)
    print(f"- Total people analyzed: {diversity_analysis['summary']['total_people_analyzed']}")
    print(f"- People with unused roles: {diversity_analysis['summary']['people_with_unused_roles']}")
    print(f"- Average completion: {diversity_analysis['summary']['average_completion_percentage']:.1%}")
    
    if diversity_analysis['underutilized_people']:
        print(f"- Underutilized people: {', '.join(diversity_analysis['underutilized_people'][:3])}")
    
    # Generate roster
    print(f"\nGenerating roster for {test_date}...")
    print("-" * 40)
    
    try:
        roster_data = generate_roster(test_date, save_to_db=True)
        
        print("-" * 40)
        print(f"Roster Generation Completed Successfully!")
        print(f"\nRoster Summary:")
        print(f"- Producer: {roster_data['producer']['name']}")
        print(f"- Assistant Producer: {roster_data['assistant_producer']['name']}")
        print(f"- Services with assignments: {len(roster_data['services'])}")
        print(f"- Hospitality team: {len(roster_data['hospitality'])} people")
        print(f"- Social media: {len(roster_data['social_media'])} people")
        
        # Show service assignments
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
    
    # Get updated statistics
    print(f"\nUpdated Assignment Statistics:")
    stats = get_assignment_statistics(lookback_days=30)
    print(f"- Total assignments analyzed: {stats['total_assignments']}")
    print(f"- Period: {stats['period']}")
    
    # Show diversity improvements
    if 'diversity_analysis' in stats:
        new_analysis = stats['diversity_analysis']
        print(f"- People with unused roles: {new_analysis['summary']['people_with_unused_roles']}")
        print(f"- Average completion: {new_analysis['summary']['average_completion_percentage']:.1%}")
    
    print("\n" + "=" * 60)
    print("ENHANCED SCHEDULER TEST COMPLETED")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    test_enhanced_scheduler()
