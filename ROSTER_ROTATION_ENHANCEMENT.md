# Roster Rotation Enhancement

## Overview
The roster generator in `scheduler.py` has been enhanced with an effective rotation system that switches people around according to their roles assigned to them. This happens automatically after every generate roster request from the frontend.

## Key Improvements

### 1. **Assignment History Tracking**
- The system now loads assignment history from the past 90 days
- Tracks how often each person has been assigned to specific roles
- Uses this data to make intelligent rotation decisions

### 2. **Priority-Based Selection**
- Implements a scoring system that prioritizes people who haven't been assigned recently
- Lower score = higher priority for assignment
- Factors considered:
  - Recent assignments to the same role (heavily weighted)
  - Total recent assignments across all roles (moderate weight)
  - Random factor for tie-breaking (minimal weight)

### 3. **Smart Rotation Logic**
- **Producer Selection**: Uses rotation logic while maintaining producer requirements
- **Assistant Producer**: Rotates fairly among eligible candidates
- **Service Roles**: Each role (Camera 1, Camera 2, Projecting, etc.) rotates based on assignment history
- **Hospitality**: Selects 2 people using rotation logic
- **Social Media**: Maintains Victor Reuben preference but considers rotation if he's been assigned recently

### 4. **Automatic Database Tracking**
- Every generated roster is automatically saved to the database
- Enables the system to track assignment patterns over time
- Creates a feedback loop for better future rotation decisions

## New Features

### 1. **Assignment Statistics API**
New endpoint: `GET /api/assignment-statistics/?days=90`

Returns detailed statistics about assignments including:
- Person-wise assignment counts and role distribution
- Role-wise assignment counts and people distribution
- Total assignments in the specified period

### 2. **Enhanced Generate Roster Function**
```python
def generate_roster(target_date: date, save_to_db: bool = True) -> Dict:
```
- Automatically saves generated rosters for tracking (can be disabled)
- Uses advanced rotation logic instead of random selection

### 3. **Statistics Helper Function**
```python
def get_assignment_statistics(lookback_days: int = 90) -> Dict:
```
- Provides insights into assignment patterns
- Helps administrators understand rotation effectiveness

## How It Works

### 1. **When Frontend Generates Roster**
1. System loads assignment history from past 90 days
2. Calculates priority scores for each person-role combination
3. Selects people with lowest scores (least recently assigned) for each role
4. Automatically saves the new roster to database for future rotation tracking

### 2. **Priority Score Calculation**
```
Score = (Recent same-role assignments × 10) + (Total recent assignments × 2) + (Random factor × 0.5)
```

### 3. **Rotation Benefits**
- **Fair Distribution**: Everyone gets equal opportunities across different roles
- **Skill Development**: People rotate through various positions
- **Prevents Favoritism**: System-based assignment reduces manual bias
- **Workload Balance**: Distributes responsibilities evenly

## Usage

### For Frontend Developers
The existing API endpoints work the same way:
- `POST /api/rosters/generate/` - Now includes automatic rotation
- `GET /api/assignment-statistics/` - New endpoint for viewing rotation statistics

### For Administrators
- Monitor rotation effectiveness using the statistics endpoint
- System automatically balances assignments over time
- No manual intervention needed for fair rotation

## Configuration

### Lookback Period
The system looks back 90 days by default. This can be adjusted in the `_load_assignment_history` method.

### Special Preferences
- Victor Reuben still gets preference for Social Media role
- Producers are selected from people marked as `is_producer=True`
- System respects role assignments (people can only be assigned to roles they're qualified for)

## Migration Notes

### Backward Compatibility
- All existing API endpoints work unchanged
- Existing database structure is preserved
- Legacy functions still available for compatibility

### Performance
- Assignment history is loaded once per roster generation
- Database queries are optimized with select_related and prefetch_related
- Minimal performance impact due to efficient algorithms

## Future Enhancements

### Possible Improvements
1. **Weighted Role Rotation**: Some roles could have different rotation weights
2. **Seasonal Adjustments**: Account for holidays or special events
3. **Skill-Based Rotation**: Consider skill levels for certain roles
4. **Advanced Analytics**: More detailed reporting and visualization

## Testing

The system has been designed to:
- Fallback to random selection if rotation logic fails
- Handle edge cases gracefully
- Maintain existing functionality while adding rotation benefits
- Provide clear logging for debugging

This enhancement ensures that the roster generator is now much more effective at distributing assignments fairly while maintaining all existing functionality and requirements.
