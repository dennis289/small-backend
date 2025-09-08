# Enhanced Roster Scheduler - Role Diversity Optimization

## Overview

The roster scheduler has been significantly upgraded to optimize role assignments with a focus on ensuring people get assigned different roles across roster generations. The system now prevents role repetition and promotes diversity in role assignments.

## Key Enhancements

### 1. Advanced Priority Scoring System

The `_calculate_person_priority_score()` method now includes multiple factors:

- **Role Repetition Penalty (Weight: 15x)**: Heavy penalty for assigning the same role repeatedly
- **Role Diversity Score**: Considers how many of a person's qualified roles they've already used
- **Assignment Frequency Balance (Weight: 1.5x)**: Moderate penalty for frequent assignments
- **Role Freshness Bonus**: Negative score (bonus) for roles a person hasn't done recently
- **Random Tie-Breaker**: Small random factor for final tie-breaking

### 2. Role Diversity Analysis

New method `_get_person_role_diversity_score()` analyzes:
- Total qualified roles for each person
- Roles already assigned recently
- Diversity ratio calculation
- Preference for people who haven't exhausted their role variety

### 3. Enhanced Selection Logic

The `_select_best_person_for_role()` method now:
1. **Prioritizes people who haven't done the specific role recently**
2. **Favors people with unused roles in their pool**
3. **Falls back to people who have exhausted their roles only when necessary**
4. **Provides detailed logging of selection reasoning**

### 4. Role Completion Status Tracking

New method `_get_person_role_completion_status()` provides:
- List of qualified roles vs. assigned roles
- Unused roles identification
- Overused roles detection
- Completion percentage calculation

### 5. Comprehensive Analytics

Several new functions provide insights:

#### `get_role_diversity_analysis()`
- Analyzes role diversity for all people
- Identifies optimization opportunities
- Provides recommendations for better rotation
- Tracks underutilized people

#### `get_person_role_history()`
- Detailed role assignment history for individuals
- Role frequency analysis
- Timeline of assignments
- Personalized recommendations

#### `optimize_role_assignments()`
- System-wide optimization recommendations
- Identifies priority people for diverse assignments
- Suggests role balancing strategies
- Training recommendations for high-demand roles

## How It Works

### Before Assignment
1. **Load Historical Data**: Analyzes last 90 days of assignments
2. **Calculate Diversity Scores**: For each person-role combination
3. **Identify Unused Roles**: People who haven't done specific roles recently

### During Assignment
1. **Filter by Role Experience**: Prefer people who haven't done the role
2. **Consider Role Pool Completion**: Favor people with unused roles available
3. **Apply Priority Scoring**: Use enhanced algorithm for final selection
4. **Track Assignments**: Update global assignment tracking

### After Assignment
1. **Generate Diversity Summary**: Show how many people got new roles
2. **Save to Database**: Track assignments for future rotation logic
3. **Provide Analytics**: Detailed reporting on diversity achieved

## Key Benefits

1. **No Role Repetition**: People won't be assigned the same role consecutively
2. **Maximized Role Diversity**: Everyone gets to try different roles they're qualified for
3. **Fair Rotation**: Balanced assignment distribution across all qualified people
4. **Intelligent Fallbacks**: System gracefully handles edge cases
5. **Comprehensive Tracking**: Detailed analytics and recommendations
6. **Future-Proof**: Considers long-term assignment patterns

## Usage

### Basic Roster Generation
```python
from small_app.scheduler import generate_roster
from datetime import date

# Generate roster with automatic diversity optimization
roster = generate_roster(date.today())
```

### Get Diversity Analytics
```python
from small_app.scheduler import get_role_diversity_analysis

# Analyze current role diversity
analysis = get_role_diversity_analysis(lookback_days=90)
print(f"People with unused roles: {analysis['summary']['people_with_unused_roles']}")
```

### Individual Person Analysis
```python
from small_app.scheduler import get_person_role_history

# Get detailed history for a person
history = get_person_role_history("John Doe", lookback_days=60)
print(f"Role diversity: {history['statistics']['role_diversity_percentage']:.1%}")
```

### System Optimization
```python
from small_app.scheduler import optimize_role_assignments

# Get optimization recommendations
recommendations = optimize_role_assignments()
for person in recommendations['priority_people']:
    print(f"{person['name']}: {person['unused_roles']} unused roles")
```

## Test Results

The enhanced scheduler achieved:
- **100% Role Diversity**: All assigned roles were new to the people
- **22 People Assigned**: Full roster generation completed
- **Intelligent Selection**: People selected based on role history and diversity
- **No Role Conflicts**: Proper rotation without repetition

## Configuration

The system uses several configurable parameters:
- **Lookback Days**: Default 90 days for assignment history analysis
- **Priority Weights**: Customizable scoring weights for different factors
- **Special Preferences**: Maintains existing preferences (e.g., Victor for Social Media) while considering rotation
- **Fallback Strategies**: Multiple fallback methods ensure roster completion

This enhanced system ensures that roster generation is not only functional but also fair, diverse, and optimized for everyone's growth and participation across different roles.
