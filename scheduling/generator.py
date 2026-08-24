"""Roster generation — decides who does what on a given date.

The generator is *fully data-driven*: it has no hardcoded roles or events. Everything
comes from the tenant's ``Roles`` and ``Events`` rows, so two clients with completely
different vocabularies both work.

Pipeline for one ``generate()`` call:

  1. **Load history.** Every ``Assignment`` from the last 90 days becomes two tallies:
     how often a person did each role, and how often each role went to each person.
     These drive the fairness score.
  2. **Load cooldowns.** The last ``COOLDOWN_GENERATIONS`` (3) *roster dates* form a
     hard block-list: if you did role X on any of them, you're not eligible for X.
     The most recent date is remembered separately as a weaker back-to-back guard.
  3. **Pick leadership.** Producer, then assistant producer, from the people flagged
     ``is_producer`` / ``is_assistant_producer``.
  4. **Reserve the assistant's second job.** One event role they hold is held back
     for them, so supporting the producer *plus* one more job is guaranteed.
  5. **Fill each event's roles.** Only roles bound to that event, only people who hold
     that role, one person per role.
  6. **Fill special roles.** Once per day rather than per event, up to each role's
     ``max_assignments``.

The allocation rules, in the order they take precedence:

  * **The producer only produces.** Once chosen they take no other job, and they are
    never reused to plug a gap.
  * **The assistant producer takes exactly one more role**, reserved up front.
  * **One job per person** otherwise — being assigned anything removes you from the
    pool, which spreads work as widely as the team allows.
  * **Nobody does the same role twice on one roster.** This is the rule that survives
    even when the one-job rule cannot.
  * **Too few people? Reuse rather than leave blanks.** When everyone capable is
    already working, the slot goes to whoever is carrying the fewest jobs today. A
    slot is only left empty when filling it would mean repeating a role or using the
    producer.

Selection within an eligible pool is *lowest score wins* — see
``_calculate_person_priority_score`` — with a tie window so the result varies between
runs instead of being deterministic.

Nothing here writes to the database. Persistence is a separate, explicit step
(``save_roster_to_database``), called only once a human has approved the roster.
That's why history only reflects rosters that were actually saved.
"""

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from django.db import transaction
from django.db.models import QuerySet

from small_app.models import Assignment, Events, Persons, Roles, Rosters

logger = logging.getLogger(__name__)


@dataclass
class RoleAssignment:
    """One filled (or deliberately empty) slot in an event.

    ``person_id`` is None and ``name`` is "" when no eligible person was found —
    the frontend renders that as "Unassigned — edit to fill".
    """
    role: str
    name: str
    person_id: Optional[int]


class RosterGenerator:
    """Fully dynamic roster generator — all roles and events come from the database."""

    COOLDOWN_GENERATIONS = 3  # Generations a person must sit out before repeating a role

    # Producing and assisting are one job for rotation purposes. Most people flagged
    # for one are flagged for the other, so treating them as separate roles let the
    # same small group swap seats week after week while the cooldown saw two clean
    # rotations. Doing either puts you on cooldown for both.
    LEADERSHIP_ROLES = frozenset({'producer', 'assistant producer'})

    def __init__(self, client=None):
        # All queries and writes are scoped to this client (tenant). Passing None
        # means "no tenant", which matches no rows — never pass None from a request.
        self.client = client
        # Person IDs already given a job in this generation, so nobody is double-booked.
        self.global_assigned: Set[int] = set()
        # person_id -> {role_name_lower: times done in the lookback window}
        self.assignment_history: Dict[int, Dict[str, int]] = {}
        # role_name_lower -> {person_id: times they did it in the lookback window}
        self.role_assignment_counts: Dict[str, Dict[int, int]] = {}
        # person_id -> {role names they're blocked from this round}
        self.generation_cooldown: Dict[int, Set[str]] = {}
        # Who held each role in the immediately previous saved roster. Used to
        # guarantee no back-to-back repeats even when the full cooldown pool is exhausted.
        self.previous_roster_holders: Dict[str, Set[int]] = {}
        # person_id -> role names (lowercased) they already hold *on this roster*.
        # Drives both the same-role-twice rule and "who is carrying least today"
        # when there are too few people and someone has to double up.
        self.today_roles: Dict[int, Set[str]] = {}
        self._producer_id: Optional[int] = None
        self._assistant_producer_id: Optional[int] = None
        self._assistant_producer: Optional[Persons] = None
        # (event_pk, role_pk) held back for the assistant producer's second job.
        self._ap_reserved_slot: Optional[tuple] = None

    # ------------------------------------------------------------------
    # Per-roster bookkeeping
    # ------------------------------------------------------------------

    def _record_assignment(self, person_id: int, role_name: str) -> None:
        """Mark a person as working this roster, in this role.

        ``global_assigned`` is the one-job-per-person rule; ``today_roles`` is the
        finer record needed when that rule has to be relaxed because there aren't
        enough people to go round.
        """
        self.global_assigned.add(person_id)
        self.today_roles.setdefault(person_id, set()).add(role_name.lower())

    def _jobs_today(self, person_id: int) -> int:
        return len(self.today_roles.get(person_id, set()))

    def _holds_role_today(self, person_id: int, role_name: str) -> bool:
        return role_name.lower() in self.today_roles.get(person_id, set())

    # ------------------------------------------------------------------
    # History & cooldown helpers
    # ------------------------------------------------------------------

    def _load_assignment_history(self, target_date: date, lookback_days: int = 90) -> None:
        """Load assignment history from the last N days to inform rotation decisions."""
        start_date = target_date - timedelta(days=lookback_days)

        recent_assignments = Assignment.objects.filter(
            client=self.client,
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
        self.previous_roster_holders.clear()

        recent_dates = list(
            Rosters.objects
            .filter(client=self.client, date__lt=target_date)
            .values_list('date', flat=True)
            .distinct()
            .order_by('-date')[:self.COOLDOWN_GENERATIONS]
        )
        # Rosters saved *after* the target date count too. Weeks aren't always built
        # in order — filling a gap between two saved weeks is normal — and a repeat
        # one week in the future is just as much a repeat as one in the past.
        upcoming_dates = list(
            Rosters.objects
            .filter(client=self.client, date__gt=target_date)
            .values_list('date', flat=True)
            .distinct()
            .order_by('date')[:self.COOLDOWN_GENERATIONS]
        )

        # No prior dates is not a reason to skip: a roster may already be saved for
        # the target date itself, and regenerating it should still avoid repeats.
        most_recent_date = recent_dates[0] if recent_dates else None
        next_date = upcoming_dates[0] if upcoming_dates else None

        cooldown_assignments = Assignment.objects.filter(
            client=self.client,
            roster__date__in=recent_dates + upcoming_dates
        ).select_related('person', 'role', 'roster')

        # A roster already saved for the target date itself. Regenerating a date must
        # not reproduce what is already stored for it — that reads as the algorithm
        # ignoring rotation entirely — so its holders are blocked too. It is excluded
        # from `recent_dates` above by `date__lt`, which is correct for the
        # three-generation window: this is the date being replaced, not a prior one.
        existing_today = Assignment.objects.filter(
            client=self.client, roster__date=target_date
        ).select_related('person', 'role')

        for assignment in list(cooldown_assignments) + list(existing_today):
            person_id = assignment.person.pk
            role_name = assignment.role.name.lower()

            # Leadership is one bucket: having produced blocks assisting and vice
            # versa, so the two jobs rotate through the team together rather than a
            # handful of people trading places.
            blocked = (
                self.LEADERSHIP_ROLES if role_name in self.LEADERSHIP_ROLES
                else {role_name}
            )
            self.generation_cooldown.setdefault(person_id, set()).update(blocked)
            # The dates immediately either side, plus this date's own saved roster,
            # form the back-to-back guard that survives even when the full cooldown
            # pool is exhausted.
            if assignment.roster.date in (most_recent_date, next_date, target_date):
                for blocked_role in blocked:
                    self.previous_roster_holders.setdefault(blocked_role, set()).add(person_id)

    def _is_on_cooldown(self, person_id: int, role_name: str) -> bool:
        return role_name.lower() in self.generation_cooldown.get(person_id, set())

    def _held_role_in_previous_roster(self, person_id: int, role_name: str) -> bool:
        return person_id in self.previous_roster_holders.get(role_name.lower(), set())

    def _filter_cooldown(self, people: List[Persons], role_name: str) -> List[Persons]:
        """Apply rotation rules with a two-tier fallback.

        Tier 1 (preferred): everyone not on cooldown.
        Tier 2 (fallback): cooldown is exhausted — still exclude whoever held the role
        in the immediately previous saved roster so the same person never repeats back-to-back.
        Tier 3 (last resort): only one person exists for the role; we have no choice.
        """
        available = [p for p in people if not self._is_on_cooldown(p.pk, role_name)]
        if available:
            return available
        no_back_to_back = [p for p in people if not self._held_role_in_previous_roster(p.pk, role_name)]
        if no_back_to_back:
            return no_back_to_back
        return people

    # ------------------------------------------------------------------
    # Scoring & selection helpers
    # ------------------------------------------------------------------

    def _calculate_person_priority_score(self, person: Persons, role_name: str) -> float:
        """Fairness score for one candidate — **lower is better**.

        Three components:
          * +10 per time they've done *this* role recently — the dominant term, so
            role variety is preferred over anything else;
          * +2 per assignment of *any* kind recently — spreads total workload;
          * +0..0.5 random — breaks exact ties so identical candidates aren't
            always resolved in database order.

        Someone brand new scores ~0 and therefore wins over everyone else.
        """
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

    # Candidates within this many score points of the minimum are treated as tied
    # and picked among randomly. Higher = more randomization, lower = stricter fairness.
    SCORE_TIE_WINDOW = 10.0

    def _select_best_person_for_role(self, eligible_people: List[Persons], role_name: str) -> Optional[Persons]:
        """Pick one person from an already-eligible pool.

        Scores everyone, then picks at random among those within
        ``SCORE_TIE_WINDOW`` of the best score. Since the window (10.0) equals one
        role-repeat penalty, someone who has done this role once is treated as tied
        with someone who never has — deliberate slack that keeps consecutive weeks
        from looking mechanical.
        """
        if not eligible_people:
            return None
        scored_people = [
            (self._calculate_person_priority_score(person, role_name), person)
            for person in eligible_people
        ]
        min_score = min(score for score, _ in scored_people)
        tied = [person for score, person in scored_people if score <= min_score + self.SCORE_TIE_WINDOW]
        return random.choice(tied)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_initial_data(self, events: QuerySet, roles: List[Roles], available_people: QuerySet) -> None:
        """Fail fast with a message the UI can show, rather than producing an empty roster."""
        if not events.filter(is_active=True).exists():
            raise ValueError("No events defined.")
        if not roles:
            raise ValueError("No roles defined.")
        if not available_people.filter(is_active=True, is_present=True).exists():
            raise ValueError("No people marked as present for the selected date.")

    # ------------------------------------------------------------------
    # Leadership selection
    # ------------------------------------------------------------------

    def _select_producer(self, available_people: QuerySet) -> Persons:
        """Pick the day's producer from people flagged ``is_producer``.

        Raises ValueError if nobody qualifies — a roster without a producer is
        considered invalid rather than partially generated.
        """
        producer_pool = list(available_people.filter(is_producer=True, is_active=True, is_present=True))
        if not producer_pool:
            raise ValueError("No producer available.")
        candidates = self._filter_cooldown(producer_pool, "producer")
        producer = self._select_best_person_for_role(candidates, "producer")
        if not producer:
            producer = random.choice(candidates)
        # The producer produces and nothing else — they are never reused to fill a
        # gap, even when people are short. See ``_select_reuse_candidate``.
        self._producer_id = producer.pk
        self._record_assignment(producer.pk, "producer")
        return producer

    def _select_assistant_producer(self, available_people: QuerySet) -> Persons:
        """Pick the assistant producer, excluding whoever just became producer."""
        assistant_pool = list(
            available_people.filter(is_assistant_producer=True, is_active=True, is_present=True)
            .exclude(pk__in=self.global_assigned)
        )
        if not assistant_pool:
            raise ValueError("No assistant producer available.")
        candidates = self._filter_cooldown(assistant_pool, "assistant producer")
        assistant = self._select_best_person_for_role(candidates, "assistant producer")
        if not assistant:
            assistant = random.choice(candidates)
        # The assistant producer supports the producer *and* carries exactly one more
        # job. Rather than leaving them in the general pool and hoping they win a
        # role on score, they're marked assigned here and a slot is reserved for them
        # by ``_reserve_assistant_slot`` — which is what makes the second job a
        # guarantee rather than a coincidence.
        self._assistant_producer_id = assistant.pk
        self._assistant_producer = assistant
        self._record_assignment(assistant.pk, "assistant producer")
        return assistant

    def _reserve_assistant_slot(self, events: QuerySet) -> None:
        """Hold one event role back for the assistant producer's second job.

        Picks the role that suits them best on the same fairness score used
        everywhere else, so the reserved slot is one they're due rather than an
        arbitrary one. A role they're on cooldown for is heavily penalised but still
        usable — the guarantee of a second job outranks rotation preference.

        Does nothing when the assistant holds no other role, or none of their roles
        is bound to an active event: there is simply no second job to give them.
        """
        assistant = self._assistant_producer
        if assistant is None:
            return

        assistant_roles = set(assistant.roles.all())
        candidates = []
        for event in events:
            for role in event.roles.all():
                if role.is_special_role or not role.is_active:
                    continue
                if role not in assistant_roles:
                    continue
                score = self._calculate_person_priority_score(assistant, role.name)
                on_cooldown = self._is_on_cooldown(assistant.pk, role.name)
                candidates.append((on_cooldown, score, event.pk, role.pk))

        if not candidates:
            logger.info(
                "Assistant producer holds no other active event role — no second job reserved"
            )
            return

        # Rotation is a hard preference, not a weighting: a role they are off
        # cooldown for always beats one they aren't, however the fairness scores
        # compare. Only when every one of their roles is on cooldown does the
        # guarantee of a second job win, and that is logged so the reason a repeat
        # appeared is traceable.
        clean = [c for c in candidates if not c[0]]
        pool = clean or candidates
        if not clean:
            logger.info(
                "Assistant producer %s is on cooldown for every role they hold — "
                "reserving a repeat to honour the second-job guarantee",
                assistant.pk,
            )

        pool.sort(key=lambda c: c[1])
        _, _, event_pk, role_pk = pool[0]
        self._ap_reserved_slot = (event_pk, role_pk)

    def _select_reuse_candidate(
        self, capable: List[Persons], role_name: str
    ) -> Optional[Persons]:
        """Last resort when everyone capable is already working today.

        Rather than leaving the slot blank, reuse someone — but never for a role they
        already hold on this roster, and never either leader. The producer only
        produces; the assistant producer supports them and does exactly one more job,
        and "exactly one" has to mean it even when the team is short, or the guarantee
        turns into a floor rather than a rule.

        Whoever is carrying the fewest jobs today goes first, so doubling-up spreads
        evenly instead of landing repeatedly on the same person.
        """
        leaders = {self._producer_id, self._assistant_producer_id}
        pool = [
            p for p in capable
            if p.pk not in leaders and not self._holds_role_today(p.pk, role_name)
        ]
        if not pool:
            return None

        # Rotation first: reuse is not an excuse to hand someone the role they had
        # last week. ``_filter_cooldown`` degrades on its own when the role is too
        # thinly staffed to honour the full cooldown, so this never empties the pool.
        rotation_preferred = self._filter_cooldown(pool, role_name)

        fewest = min(self._jobs_today(p.pk) for p in rotation_preferred)
        least_loaded = [p for p in rotation_preferred if self._jobs_today(p.pk) == fewest]
        return self._select_best_person_for_role(least_loaded, role_name)

    # ------------------------------------------------------------------
    # Dynamic role assignment
    # ------------------------------------------------------------------

    def _assign_all_event_roles(
        self, events: QuerySet, available_people: QuerySet
    ) -> Dict[int, List[RoleAssignment]]:
        """Fill every event's non-special roles, across all events in one pass.

        Slots are decided in display order, event by event.

        **Do not "optimise" this to fill the scarcest role first.** It looks like the
        obvious improvement — a role only four people can do surely deserves first
        pick — but it was measured on real tenant data over 12 six-week simulations
        and made rotation *four times worse*: 12.1 avoidable same-role repeats versus
        2.9, with no reduction in blanks. Giving a thin role first pick forces its tiny
        pool to serve every single generation, which exhausts that role's cooldown
        immediately and simultaneously locks those people out of the roles they could
        have covered. Leaving it in display order lets scarce-role people sometimes be
        used elsewhere, and spreads the unavoidable repeats around.
        """
        # Build every slot to fill: one per (event, non-special active role).
        slots = []
        capability: Dict[int, List[Persons]] = {}
        for event in events:
            for position, role in enumerate(
                [r for r in event.roles.all() if r.is_active and not r.is_special_role]
            ):
                if role.pk not in capability:
                    capability[role.pk] = [
                        p for p in available_people
                        if p.is_active and p.is_present and role in p.roles.all()
                    ]
                slots.append({
                    'event': event,
                    'role': role,
                    'position': position,
                    'assignment': None,
                })

        for slot in slots:
            slot['assignment'] = self._fill_slot(
                slot['event'], slot['role'], capability[slot['role'].pk]
            )

        # Regroup by event, back in display order.
        by_event: Dict[int, List[RoleAssignment]] = {}
        for slot in slots:
            if slot['assignment'] is None:
                continue
            by_event.setdefault(slot['event'].pk, []).append(slot['assignment'])
        return by_event

    def _fill_slot(
        self, event: Events, role: Roles, capable: List[Persons]
    ) -> Optional[RoleAssignment]:
        """Choose one person for a single (event, role) slot.

        Returns None when the role should not appear at all — nobody is configured
        for it, which is the normal case for the auto-created "Producer" /
        "Assistant Producer" roles. A slot that *should* exist but could not be
        filled comes back with ``person_id=None`` for a human to complete.
        """
        role_name = role.name

        # The slot held back for the assistant producer's guaranteed second job.
        if self._ap_reserved_slot == (event.pk, role.pk) and self._assistant_producer:
            assistant = self._assistant_producer
            self._record_assignment(assistant.pk, role_name)
            return RoleAssignment(
                role=role_name,
                name=f"{assistant.first_name} {assistant.last_name}",
                person_id=assistant.pk,
            )

        if not capable:
            # Nobody is configured for this role — skip silently.
            return None

        not_yet_assigned = [p for p in capable if p.pk not in self.global_assigned]
        eligible = self._filter_cooldown(not_yet_assigned, role_name)

        chosen = None
        if eligible:
            chosen = self._select_best_person_for_role(eligible, role_name)
            if not chosen:
                chosen = random.choice(eligible)
        else:
            # Everyone who can do this role is already working today. Reuse the
            # least-loaded of them rather than leaving the slot blank — a real
            # roster with a small team needs people to double up.
            chosen = self._select_reuse_candidate(capable, role_name)
            if chosen:
                logger.info(
                    "Reusing %s for role '%s' in event '%s' — no unassigned person left",
                    chosen.pk, role_name, event.name,
                )

        if chosen:
            self._record_assignment(chosen.pk, role_name)
            return RoleAssignment(
                role=role_name,
                name=f"{chosen.first_name} {chosen.last_name}",
                person_id=chosen.pk,
            )

        # Genuinely nobody left: everyone capable already holds this very role
        # today, or the only candidate is the producer. Leave it for a human rather
        # than breaking one of the two hard rules.
        logger.info(
            "No one available for role '%s' in event '%s' — leaving slot empty",
            role_name, event.name
        )
        return RoleAssignment(role=role_name, name="", person_id=None)

    def _assign_special_roles(self, available_people: QuerySet, roles: List[Roles]) -> Dict[str, List[Dict]]:
        """Assign special roles once for the whole day, across all events.

        Each role takes up to its ``max_assignments`` people, chosen one at a time so
        each pick sees the pool shrink. Returns ``{role_name_lower: [{person_id, name}]}``
        — the lowercase key is what ``_save_special_role_assignments`` matches back to
        a ``Roles`` row, so role names must stay unique case-insensitively.
        """
        result: Dict[str, List[Dict]] = {}
        special_roles = [r for r in roles if r.is_special_role]

        for role in special_roles:
            role_name = role.name
            max_count = role.max_assignments

            capable = [
                p for p in available_people
                if p.is_active and p.is_present and role in p.roles.all()
            ]
            if not capable:
                continue

            not_yet_assigned = [p for p in capable if p.pk not in self.global_assigned]
            candidates = self._filter_cooldown(not_yet_assigned, role_name)

            selected = []
            remaining = list(candidates)
            for _ in range(min(max_count, len(remaining))):
                best = self._select_best_person_for_role(remaining, role_name)
                if best:
                    selected.append(best)
                    remaining.remove(best)

            if not selected and candidates:
                selected = random.sample(candidates, min(max_count, len(candidates)))

            # Short of people: top the role up by reusing whoever is carrying least
            # today, on the same terms as event roles — never the producer, and never
            # someone who already holds this role on this roster.
            while len(selected) < max_count:
                already_chosen = {p.pk for p in selected}
                reuse_pool = [p for p in capable if p.pk not in already_chosen]
                extra = self._select_reuse_candidate(reuse_pool, role_name)
                if not extra:
                    break
                logger.info(
                    "Reusing %s for special role '%s' — no unassigned person left",
                    extra.pk, role_name,
                )
                selected.append(extra)

            if not selected:
                logger.warning("No one available for special role '%s'", role_name)

            result[role_name.lower()] = [
                {"person_id": p.pk, "name": f"{p.first_name} {p.last_name}"}
                for p in selected
            ]
            for person in selected:
                self._record_assignment(person.pk, role_name)

        return result

    # ------------------------------------------------------------------
    # Main generation
    # ------------------------------------------------------------------

    def generate(
        self,
        target_date: date,
        inactive_events: Optional[List[int]] = None,
        absent_members: Optional[List[int]] = None,
    ) -> Dict:
        """Generate a roster for the given date — fully driven by database roles.

        ``inactive_events`` and ``absent_members`` exclude events/people for this
        single generation only — they do not mutate the persisted ``is_active`` /
        ``is_present`` flags.
        """
        logger.info("Starting roster generation for date: %s", target_date)

        self.global_assigned.clear()
        # Per-roster state, so reusing one generator instance for several dates
        # can't leak one roster's assignments into the next.
        self.today_roles.clear()
        self._producer_id = None
        self._assistant_producer_id = None
        self._assistant_producer = None
        self._ap_reserved_slot = None
        self._load_assignment_history(target_date)

        events = Events.objects.filter(
            client=self.client, is_active=True
        ).order_by('id').prefetch_related('roles')
        if inactive_events:
            events = events.exclude(id__in=inactive_events)
        # Inactive roles are skipped here only. Rosters already saved keep their
        # assignments to a since-deactivated role, so re-exporting an old PDF still
        # reproduces what was actually served that day.
        roles = list(Roles.objects.filter(client=self.client, is_active=True))
        available_people = Persons.objects.filter(
            client=self.client, is_present=True, is_active=True
        ).prefetch_related('roles')
        if absent_members:
            available_people = available_people.exclude(id__in=absent_members)

        self._validate_initial_data(events, roles, available_people)

        # Leadership
        producer = self._select_producer(available_people)
        assistant_producer = self._select_assistant_producer(available_people)
        # Hold one event role back for the assistant before general allocation runs,
        # so their second job is guaranteed rather than left to the scoring.
        self._reserve_assistant_slot(events)

        # Event roles.
        special_role_pool: Dict[int, Roles] = {}
        for event in events:
            for r in event.roles.all():
                if r.is_special_role and r.is_active:
                    special_role_pool[r.pk] = r

        assignments_by_event = self._assign_all_event_roles(events, available_people)

        event_list = []
        for event in events:
            event_list.append({
                "event_id": event.pk,
                "event_name": event.name or event.description or "Unknown Event",
                "assignments": [
                    {"role": a.role, "name": a.name, "person_id": a.person_id}
                    for a in assignments_by_event.get(event.pk, [])
                ],
            })

        # Special roles — only those bound to at least one active event.
        # Re-sort the union: the pool was filled event by event, so a role bound only
        # to a later event would otherwise land ahead of a lower-ordered one.
        special_roles = self._assign_special_roles(
            available_people,
            sorted(special_role_pool.values(), key=lambda r: (r.display_order, r.name)),
        )

        logger.info("Roster generated successfully. Total assigned: %d", len(self.global_assigned))

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
        """Persist an approved roster payload — the only method here that writes.

        For each active event present in the payload it gets-or-creates the
        ``Rosters`` row for ``(event, target_date)``, wipes that roster's existing
        assignments, and re-creates them from the payload. Re-saving a date is
        therefore idempotent rather than additive.

        Leadership and special roles are attached to the *first* roster of the day
        (they're day-level, not event-level, but ``Assignment`` requires a roster).
        Anything the payload references that no longer exists is logged and skipped.
        The whole thing runs in one transaction.
        """
        try:
            with transaction.atomic():
                events = Events.objects.filter(client=self.client, is_active=True)
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
                        defaults={'client': self.client},
                    )

                    if first_roster_entry is None:
                        first_roster_entry = roster_entry

                    # Clear existing assignments for this roster entry
                    Assignment.objects.filter(roster=roster_entry).delete()

                    # Enumerate so the row's position in the payload — the order the
                    # scheduler dragged it into — is what gets stored.
                    for position, assignment_data in enumerate(event_data.get('assignments', [])):
                        # A deliberately empty slot — nobody could fill it without
                        # breaking a rule. Not an error, so don't look it up and log
                        # a failure for it.
                        if not assignment_data.get('person_id'):
                            continue
                        try:
                            person = Persons.objects.get(
                                id=assignment_data['person_id'], client=self.client
                            )
                            role = Roles.objects.filter(
                                client=self.client, name__iexact=assignment_data['role']
                            ).first()
                            if role:
                                Assignment.objects.create(
                                    client=self.client,
                                    roster=roster_entry,
                                    role=role,
                                    person=person,
                                    display_order=Assignment.ORDER_BAND_EVENT + position,
                                )
                        except Persons.DoesNotExist as e:
                            logger.warning("Could not create assignment: %s", e)

                # Leadership + special roles saved to the first roster entry
                if first_roster_entry:
                    self._save_leadership_assignments(roster_data, first_roster_entry)
                    self._save_special_role_assignments(roster_data, first_roster_entry)

                logger.info("Roster saved to database for %s", target_date)

        except Exception as e:
            logger.exception("Error saving roster to database: %s", e)
            raise

    def _save_leadership_assignments(self, roster_data: Dict, roster_entry: Rosters) -> None:
        """Save producer / assistant producer as ordinary Assignment rows.

        Creates the "Producer" and "Assistant Producer" ``Roles`` for the client on
        first use, so leadership participates in the same cooldown and history
        machinery as every other role.
        """
        leadership = [
            ("producer", "Producer"),
            ("assistant_producer", "Assistant Producer"),
        ]
        for position, (data_key, role_display_name) in enumerate(leadership):
            person_data = roster_data.get(data_key)
            if not person_data:
                continue
            try:
                person = Persons.objects.get(id=person_data['id'], client=self.client)
            except Persons.DoesNotExist:
                logger.warning("Person not found for %s assignment", role_display_name)
                continue
            role, _ = Roles.objects.get_or_create(
                client=self.client,
                name=role_display_name,
                defaults={"description": role_display_name, "is_special_role": False},
            )
            Assignment.objects.update_or_create(
                roster=roster_entry,
                role=role,
                person=person,
                defaults={
                    'client': self.client,
                    'display_order': Assignment.ORDER_BAND_LEADERSHIP + position,
                },
            )

    def _save_special_role_assignments(self, roster_data: Dict, roster_entry: Rosters) -> None:
        """Save special-role picks, resolving the payload's lowercase keys back to Roles."""
        special_roles = roster_data.get('special_roles', {})
        # Cards keep the order they were dragged into, and people keep their order
        # within a card. Multiplying the card's position leaves room for the people
        # inside it without one card's members bleeding into the next card's band.
        for card_position, (role_key, people) in enumerate(special_roles.items()):
            role = Roles.objects.filter(client=self.client, name__iexact=role_key).first()
            if not role:
                continue
            band = Assignment.ORDER_BAND_SPECIAL + card_position * 100
            for person_position, person_data in enumerate(people):
                try:
                    person = Persons.objects.get(id=person_data['person_id'], client=self.client)
                    Assignment.objects.update_or_create(
                        roster=roster_entry,
                        role=role,
                        person=person,
                        defaults={
                            'client': self.client,
                            'display_order': band + person_position,
                        },
                    )
                except Persons.DoesNotExist:
                    logger.warning(
                        "Person %s not found for role '%s'",
                        person_data.get('person_id'), role_key
                    )
