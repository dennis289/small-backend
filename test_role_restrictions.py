#!/usr/bin/env python
"""
Test script to verify role restrictions and assignment optimization.
"""

import os
import sys
import django

# Add project path
sys.path.append('/var/www/html/personal/small_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'small_backend.settings')
django.setup()

from small_app.models import Persons, Roles, Services, Assignment, Rosters
from small_app.scheduler import generate_roster
from django.utils import timezone
from datetime import date

def test_role_restrictions():
    """
    Test the enhanced scheduler with strict role restrictions.
    """
    print("🔧 Testing Enhanced Scheduler with Role Restrictions")
    print("=" * 60)
    
    # Get data
    available_people = Persons.objects.filter(is_present=True)
    roles = list(Roles.objects.all())
    services = Services.objects.all()
    
    print(f"📊 Available People: {available_people.count()}")
    print(f"📊 Services: {services.count()}")
    print(f"📊 Roles: {len(roles)}")
    print()
    
    # Analyze people by roles
    print("👥 People Analysis:")
    producers = []
    timekeeper_media = []
    regular_people = []
    
    for person in available_people:
        person_roles = [role.name.lower() for role in person.roles.all()]
        role_list = ", ".join([role.title() for role in person_roles])
        
        if 'producer' in person_roles:
            producers.append(person)
            print(f"   🎬 {person.first_name} {person.last_name}: {role_list}")
        elif 'timekeeper' in person_roles or 'media desk' in person_roles:
            timekeeper_media.append(person)
            print(f"   ⏰ {person.first_name} {person.last_name}: {role_list}")
        else:
            regular_people.append(person)
            print(f"   👤 {person.first_name} {person.last_name}: {role_list}")
    
    print(f"\n📈 Breakdown: {len(producers)} producers, {len(timekeeper_media)} timekeeper/media, {len(regular_people)} regular")
    print()
    
    # Generate roster with new restrictions
    print("🚀 Generating Roster with Restrictions...")
    print("-" * 40)
    
    try:
        result = generate_roster(
            target_date=date.today(),
            save_to_db=False  # Don't save to avoid constraint issues
        )
        
        print(f"✅ Roster generated successfully!")
        
        # Extract assignments from the returned structure
        all_assignments = []
        
        if 'services' in result:
            services_data = result['services']
            print(f"📋 Total Services: {len(services_data)}")
            
            # Extract assignments from services
            for service_data in services_data:
                service_assignments = service_data.get('assignments', [])
                for assignment in service_assignments:
                    all_assignments.append({
                        'role': assignment['role'],
                        'name': assignment['name'], 
                        'person_id': assignment['person_id'],
                        'service': service_data.get('service_name', 'Unknown')
                    })
            
            # Add hospitality assignments
            if 'hospitality' in result and result['hospitality']:
                hospitality = result['hospitality']
                if isinstance(hospitality, list):
                    for hosp_assignment in hospitality:
                        if isinstance(hosp_assignment, dict):
                            all_assignments.append({
                                'role': 'Hospitality',
                                'name': hosp_assignment.get('name', 'Unknown'),
                                'person_id': hosp_assignment.get('person_id', 0),
                                'service': 'Hospitality'
                            })
                        elif isinstance(hosp_assignment, str):
                            all_assignments.append({
                                'role': 'Hospitality',
                                'name': hosp_assignment,
                                'person_id': 0,  # Will try to find person by name
                                'service': 'Hospitality'
                            })
                elif isinstance(hospitality, dict):
                    all_assignments.append({
                        'role': 'Hospitality',
                        'name': hospitality.get('name', 'Unknown'),
                        'person_id': hospitality.get('person_id', 0),
                        'service': 'Hospitality'
                    })
                elif isinstance(hospitality, str):
                    # Hospitality is a string (person name)
                    all_assignments.append({
                        'role': 'Hospitality',
                        'name': hospitality,
                        'person_id': 0,  # Will try to find person by name
                        'service': 'Hospitality'
                    })
            
            # Add producer assignments  
            if 'producer' in result and result['producer']:
                all_assignments.append({
                    'role': 'Producer',
                    'name': result['producer'].get('name', 'Unknown'),
                    'person_id': result['producer'].get('id', 0),
                    'service': 'Producer'
                })
            
            if 'assistant_producer' in result and result['assistant_producer']:
                all_assignments.append({
                    'role': 'Assistant Producer',
                    'name': result['assistant_producer'].get('name', 'Unknown'),
                    'person_id': result['assistant_producer'].get('id', 0),
                    'service': 'Assistant Producer'
                })
                
        else:
            print("❌ Could not find services data in result")
            return False
        
        print(f"📋 Total Assignments: {len(all_assignments)}")
        
        # Check for violations
        print("\n🔍 Checking Role Restrictions:")
        print("-" * 30)
        
        violations = []
        producer_violations = 0
        double_assignments = {}
        hospitality_cross_training = 0
        
        for assignment in all_assignments:
            if assignment['person_id'] == 0:
                # Try to find person by name
                name_parts = assignment['name'].split()
                if len(name_parts) >= 2:
                    first_name = name_parts[0]
                    last_name = ' '.join(name_parts[1:])
                    try:
                        person = available_people.get(first_name=first_name, last_name=last_name)
                    except Persons.DoesNotExist:
                        print(f"⚠️  Could not find person: {assignment['name']}")
                        continue
                else:
                    print(f"⚠️  Invalid name format: {assignment['name']}")
                    continue
            else:
                person = available_people.get(id=assignment['person_id'])
            
            person_roles = [role.name.lower() for role in person.roles.all()]
            assigned_role = assignment['role'].lower()
            person_key = assignment['name']
            
            # Track assignments per person
            if person_key not in double_assignments:
                double_assignments[person_key] = []
            double_assignments[person_key].append(assigned_role)
            
            # Check producer restrictions
            is_producer = 'producer' in person_roles
            
            if is_producer and assigned_role not in ['producer', 'assistant producer']:
                violations.append(f"❌ PRODUCER VIOLATION: {person_key} (producer) assigned to {assignment['role']}")
                producer_violations += 1
            elif not is_producer and assigned_role in ['producer', 'assistant producer']:
                violations.append(f"❌ PRODUCER VIOLATION: {person_key} (non-producer) assigned to {assignment['role']}")
                producer_violations += 1
            
            # Check hospitality cross-training
            if assigned_role == 'hospitality':
                if 'hospitality' not in person_roles:
                    if 'timekeeper' in person_roles or 'media desk' in person_roles:
                        hospitality_cross_training += 1
                        print(f"✅ Cross-training: {person_key} doing hospitality (from timekeeper/media desk)")
        
        # Check double assignments
        double_assignment_count = 0
        for person_key, assignments in double_assignments.items():
            if len(assignments) > 1:
                double_assignment_count += 1
                violations.append(f"❌ DOUBLE ASSIGNMENT: {person_key} assigned to {assignments}")
        
        # Summary
        print(f"\n📊 RESTRICTION COMPLIANCE REPORT:")
        print(f"   Producer violations: {producer_violations}")
        print(f"   Double assignments: {double_assignment_count}")
        print(f"   Hospitality cross-training: {hospitality_cross_training}")
        print(f"   Total violations: {len(violations)}")
        
        if violations:
            print(f"\n❌ VIOLATIONS FOUND:")
            for violation in violations[:10]:  # Show first 10
                print(f"   {violation}")
            if len(violations) > 10:
                print(f"   ... and {len(violations) - 10} more")
        else:
            print(f"\n✅ ALL RESTRICTIONS RESPECTED!")
        
        # Assignment distribution
        print(f"\n📈 ASSIGNMENT DISTRIBUTION:")
        assigned_people = len(double_assignments)
        total_people = available_people.count()
        utilization = (assigned_people / total_people) * 100 if total_people > 0 else 0
        
        print(f"   People assigned: {assigned_people}/{total_people} ({utilization:.1f}%)")
        print(f"   Average assignments per assigned person: {len(all_assignments)/assigned_people:.2f}")
        
        # Show unassigned people
        unassigned_people = []
        assigned_person_names = set(double_assignments.keys())
        
        for person in available_people:
            person_name = f"{person.first_name} {person.last_name}"
            if person_name not in assigned_person_names:
                person_roles = [role.name.lower() for role in person.roles.all()]
                unassigned_people.append(f"{person_name} ({', '.join(person_roles)})")
        
        if unassigned_people:
            print(f"\n👥 UNASSIGNED PEOPLE ({len(unassigned_people)}):")
            for person_info in unassigned_people[:5]:
                print(f"   {person_info}")
            if len(unassigned_people) > 5:
                print(f"   ... and {len(unassigned_people) - 5} more")
        
        return len(violations) == 0
        
    except Exception as e:
        print(f"❌ Error generating roster: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_role_restrictions()
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}: Role restriction test {'passed' if success else 'failed'}")
