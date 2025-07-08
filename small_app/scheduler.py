from django.db.models import Q
from .models import Services, Roles, Availability, Persons
from constraint import Problem, AllDifferentConstraint
from datetime import date

def generate_roster(target_date: date):
    # Fetch all service times and roles
    service_times = Services.objects.filter(is_active=True).order_by('id')  # Ensure only active services
    required_roles = Roles.objects.all()

    if not service_times.exists():
        raise ValueError("No service times defined.")
    if not required_roles.exists():
        raise ValueError("No roles defined.")

    # Fetch availabilities for the target date
    availabilities = Availability.objects.filter(
        date=target_date,
        status__in=['available', 'preferred']
    ).select_related('person', 'service_time')

    if not availabilities.exists():
        raise ValueError("No availabilities found for the selected date.")

    # Build a mapping: (person_id, service_time_id) -> status
    availability_map = {}
    for av in availabilities:
        availability_map[(av.person_id, av.service_time_id)] = av.status

    # Fetch all people who are available/preferred for at least one service time
    available_people = Persons.objects.filter(
        id__in=[av.person_id for av in availabilities]
    ).distinct().prefetch_related('roles')

    if not available_people.exists():
        raise ValueError("No people available for the selected date.")

    problem = Problem()
    variables = {}

    # For each service time and role, find eligible people
    for st in service_times:
        for role in required_roles:
            var_name = f"{st.id}-{role.id}"
            candidates = [
                p.id for p in available_people
                if role in p.roles.all() and
                (p.id, st.id) in availability_map
            ]
            if candidates:
                problem.addVariable(var_name, candidates)
                variables[var_name] = (st, role)

    # Each person can only be assigned once per day
    for person in available_people:
        person_vars = [v for v in variables if person.id in problem._variables[v]]
        if person_vars:
            problem.addConstraint(
                lambda *assignments, pid=person.id: list(assignments).count(pid) <= 1,
                person_vars
            )

    # Each role in a service time must be assigned to a different person
    for st in service_times:
        st_vars = [v for v, (st_obj, _) in variables.items() if st_obj.id == st.id]
        if len(st_vars) > 1:
            problem.addConstraint(AllDifferentConstraint(), st_vars)

    # Prefer 'preferred' status if possible
    for person in available_people:
        preferred_services = [
            av.service_time_id for av in availabilities
            if av.person_id == person.id and av.status == 'preferred'
        ]
        if preferred_services:
            unpreferred_vars = [
                v for v, (st, _) in variables.items()
                if st.id not in preferred_services and person.id in problem._variables[v]
            ]
            for v in unpreferred_vars:
                # If possible, avoid assigning this person to unpreferred slots
                problem.addConstraint(
                    lambda assignment, pid=person.id: assignment != pid,
                    [v]
                )

    # Solve the problem
    solution = problem.getSolution()
    if not solution:
        raise ValueError("No valid roster configuration found. Please check availability and roles.")

    # Prepare assignments for serialization (e.g., for API response)
    assignments = []
    for var_name, person_id in solution.items():
        st_id, role_id = map(int, var_name.split('-'))
        assignments.append({
            'service_time_id': st_id,
            'role_id': role_id,
            'person_id': person_id
        })

    return assignments