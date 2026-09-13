"""Validate and atomically apply the person's decisions and observed work."""

from app.contracts.messages.collective import (
    Activity,
    ActivityChange,
    Character,
    CollectiveSettings,
    CollectiveState,
    Decision,
    Event,
    Lane,
    Memory,
    MemoryCandidate,
    MemorySource,
    Purpose,
    Report,
    Scope,
    Speech,
    Turn,
    WorkResult,
)


class StaleDecision(Exception):
    """The intent must be reconsidered against current facts."""


def add_event(
    state: CollectiveState,
    key: str,
    kind: str,
    actor: str,
    scope: Scope,
    origin: str,
    content: str,
    now: float,
    activity_id: str | None = None,
    source: str = "",
) -> Event:
    """Save an attributed source once, retaining its original sequence."""
    if key not in state.events:
        state.events[key] = Event(
            id=key,
            sequence=len(state.events) + 1,
            kind=kind,
            actor=actor,
            scope=scope,
            origin=origin,
            content=content,
            occurred_at=now,
            activity_id=activity_id,
            source=source,
        )
    return state.events[key]


def enqueue(
    state: CollectiveState,
    character_id: str,
    trigger: Event,
    purpose: Purpose,
    lane: Lane = "conversation",
    activity_id: str | None = None,
    speech_id: str | None = None,
) -> Turn:
    """Use the saved trigger, person and purpose as the idempotency key."""
    key = f"{trigger.id}:{character_id}:{purpose}:{lane}"
    if key not in state.turns:
        state.turns[key] = Turn(
            id=key,
            character_id=character_id,
            trigger_id=trigger.id,
            origin=trigger.origin,
            purpose=purpose,
            lane=lane,
            activity_id=activity_id,
            speech_id=speech_id,
        )
    return state.turns[key]


def next_character(
    state: CollectiveState,
    characters: dict[str, Character],
    scope: Scope,
    exclude: str | None = None,
) -> str:
    """Rotate new conversations and continue with the last actual speaker."""
    candidates = [key for key in characters if key != exclude]
    if not candidates:
        return exclude or next(iter(characters))
    previous = [
        e.actor
        for e in state.events.values()
        if e.scope == scope and e.kind == "speech" and e.actor in characters
    ]
    if scope == "master" and previous and previous[-1] in candidates:
        return previous[-1]
    count = sum(
        t.purpose in {"conversation", "reflection"} for t in state.turns.values()
    )
    return candidates[count % len(candidates)]


def times_speech_allowed(
    state: CollectiveState,
    turn: Turn,
    settings: CollectiveSettings,
    now: float,
) -> bool:
    """Share one automatic Times conversation across all private reflections."""
    origin = state.events.get(turn.origin)
    if origin is None or origin.kind != "reflection" or origin.scope != "times":
        return True
    speeches = [
        event
        for event in state.events.values()
        if event.kind == "speech"
        and event.scope == "times"
        and (source := state.events.get(event.origin)) is not None
        and source.kind == "reflection"
    ]
    if sum(event.origin == turn.origin for event in speeches) >= settings.max_round:
        return False
    return all(
        event.origin == turn.origin
        for event in speeches
        if event.occurred_at > now - settings.times_interval_seconds
    )


def save_speech(
    state: CollectiveState,
    turn: Turn,
    characters: dict[str, Character],
    settings: CollectiveSettings,
    now: float,
    *,
    body: str | None = None,
    report: Report | None = None,
    consult: str | None = None,
    activity: Activity | None = None,
) -> None:
    """Persist speech and internal peer triggers independently of delivery."""
    if report is None and not times_speech_allowed(state, turn, settings, now):
        return
    trigger = state.events[turn.trigger_id]
    scope: Scope = "master" if report is not None else trigger.scope
    key = turn.id
    speech = Speech(
        id=key,
        character_id=turn.character_id,
        scope=scope,
        origin=turn.origin,
        report=report or Report(),
        body=body,
        activity_id=activity.id if activity else None,
        activity_version=activity.version if activity else None,
        status="ready" if body else "unrendered",
    )
    state.speeches[key] = speech
    event = add_event(
        state,
        f"speech:{key}",
        "speech" if body else "report",
        turn.character_id,
        scope,
        turn.origin,
        body or speech.report.model_dump_json(),
        now,
        activity_id=speech.activity_id,
    )
    if not body:
        enqueue(state, turn.character_id, event, "render", speech_id=key)
    elif scope == "times" or consult is not None:
        count = sum(
            t.origin == turn.origin and t.purpose in {"conversation", "reflection"}
            for t in state.turns.values()
        )
        if count < settings.max_round and len(characters) > 1:
            recipient = consult or next_character(
                state, characters, "times", turn.character_id
            )
            enqueue(state, recipient, event, "conversation")


def apply_change(
    state: CollectiveState,
    turn: Turn,
    change: ActivityChange,
    characters: dict[str, Character],
) -> Activity:
    """Validate owner, version and transition before committing a promise."""
    if change.action == "start":
        if change.expected_version is not None:
            raise ValueError("A new activity cannot name an existing version")
        activity = Activity(
            id=f"activity-{state.events[turn.trigger_id].sequence}-{turn.character_id}",
            owner=turn.character_id,
            objective=change.objective,
            value=change.value,
            target=change.target,
            criteria=change.criteria,
            next_step=change.next_step,
            source=turn.trigger_id,
            instruction_source=turn.trigger_id,
        )
        if not activity.next_step.strip():
            raise ValueError("Starting work requires a concrete next step")
        if activity.id in state.activities:
            raise ValueError("This trigger already started an activity")
        state.activities[activity.id] = activity
        return activity
    activity = state.activities.get(change.activity_id or "")
    if activity is None or change.expected_version != activity.version:
        raise StaleDecision("Activity version changed or target is unknown")
    if activity.status == "done":
        raise ValueError("Create a new objective instead of rewriting a completed one")
    trigger = state.events[turn.trigger_id]
    if activity.owner != turn.character_id and trigger.actor != "master":
        raise ValueError("Only the owner or master's request can control an activity")
    if not change.reason.strip():
        raise ValueError("A control or correction requires its reason")
    if change.action in {"stop", "resume", "update"} and trigger.actor != "master":
        raise ValueError("Conversation control needs a current master instruction")
    if change.action == "resume" and activity.status not in {
        "stopped",
        "sleeping",
        "waiting",
        "blocked",
    }:
        raise ValueError("The activity is not awaiting resumption")
    if change.action == "update" and activity.status == "stopped":
        raise ValueError("A stopped activity requires explicit resumption")
    if change.action == "handoff":
        if change.recipient not in characters or change.recipient == activity.owner:
            raise ValueError("Handoff needs a different configured recipient")
        if not change.next_step.strip():
            raise ValueError("Handoff must retain the remaining work")
        activity.owner = change.recipient
    activity.version += 1
    activity.instruction_source = turn.trigger_id
    activity.reason = change.reason
    activity.status = "stopped" if change.action == "stop" else "ready"
    if change.action == "resume":
        activity.runs = 0
    activity.wake_at = None
    activity.question = ""
    if change.next_step:
        activity.next_step = change.next_step
    if change.objective:
        activity.objective = change.objective
    if change.criteria:
        activity.criteria = change.criteria
    return activity


def apply_memories(
    state: CollectiveState,
    turn: Turn,
    candidates: list[MemoryCandidate],
    now: float,
) -> None:
    """Reconsider only conflicting owners; keep independently verified work."""
    assert turn.context is not None
    included = {source for item in turn.context.items for source in item.sources}
    included.add(turn.trigger_id)
    included.add(f"result:{turn.id}")
    owners = {candidate.owner for candidate in candidates}
    conflicts: set[str] = set()
    extracted = {
        key
        for key, source in state.memory_sources.items()
        if source.status == "extracted"
    }
    for owner in owners:
        if owner not in {"master", turn.character_id}:
            raise ValueError("A character cannot overwrite a peer's private memory")
        group = [candidate for candidate in candidates if candidate.owner == owner]
        if len({candidate.key for candidate in group}) != len(group):
            raise ValueError("Duplicate memory updates in one owner group")
        conflict = False
        for candidate in group:
            if (
                not candidate.sources
                or not set(candidate.sources) <= included
                or not all(source in state.events for source in candidate.sources)
            ):
                raise ValueError("Memory requires included, attributed sources")
            if owner == "master":
                if candidate.kind != "fact" or not all(
                    state.events.get(source) is not None
                    and state.events[source].actor == "master"
                    for source in candidate.sources
                ):
                    raise ValueError("Master facts require the master's own statements")
        group = [
            candidate
            for candidate in group
            if not all(f"{owner}/{source}" in extracted for source in candidate.sources)
        ]
        for candidate in group:
            current = state.memories.get(candidate.key)
            if (current.version if current else 0) != candidate.expected_version:
                conflict = True
        for candidate in group:
            for source in candidate.sources:
                state.memory_sources[f"{owner}/{source}"] = MemorySource(
                    owner=owner,
                    event_id=source,
                    status="pending" if conflict else "extracted",
                )
            if not conflict:
                state.memories[candidate.key] = Memory.model_validate(
                    candidate.model_dump(exclude={"expected_version"})
                    | {"version": candidate.expected_version + 1}
                )
        if conflict:
            conflicts.add(owner)
            event = add_event(
                state,
                f"memory:{turn.id}:{owner}",
                "memory_conflict",
                turn.character_id,
                state.events[turn.trigger_id].scope,
                turn.origin,
                "Reconsider pending memory sources against the latest note versions.",
                now,
            )
            enqueue(state, turn.character_id, event, "memory")
    if turn.purpose == "memory":
        for source in state.memory_sources.values():
            if (
                source.owner in {"master", turn.character_id}
                and source.event_id in included
            ):
                if source.owner not in conflicts:
                    source.status = "extracted"


def apply_decision(
    state: CollectiveState,
    turn: Turn,
    decision: Decision,
    characters: dict[str, Character],
    settings: CollectiveSettings,
    now: float,
) -> None:
    """Apply intent before words, so rejected promises never become speech."""
    if decision.consult is not None and (
        decision.consult not in characters or decision.consult == turn.character_id
    ):
        raise ValueError("Consultation recipient must be a configured peer")
    activity = (
        apply_change(state, turn, decision.change, characters)
        if decision.change
        else None
    )
    apply_memories(state, turn, decision.memories, now)
    if decision.speech and decision.speech.strip():
        save_speech(
            state,
            turn,
            characters,
            settings,
            now,
            body=decision.speech,
            consult=decision.consult,
            activity=activity,
        )
    else:
        _continue_silent_turn(state, turn, characters, settings, now, decision.consult)
    if decision.inspect:
        if turn.purpose != "reflection":
            raise ValueError("Read-only Codex inspection is a reflection action")
        enqueue(
            state,
            turn.character_id,
            state.events[turn.trigger_id],
            "reflection",
            "work",
        )
    turn.status = "applied"


def _continue_silent_turn(
    state: CollectiveState,
    turn: Turn,
    characters: dict[str, Character],
    settings: CollectiveSettings,
    now: float,
    consult: str | None,
) -> None:
    trigger = state.events[turn.trigger_id]
    if not times_speech_allowed(state, turn, settings, now):
        return
    if turn.purpose == "reflection" and consult is None:
        return
    if turn.purpose not in {"conversation", "reflection"} or (
        trigger.scope != "times" and consult is None
    ):
        return
    turns = [
        item
        for item in state.turns.values()
        if item.origin == turn.origin
        and item.lane == "conversation"
        and item.purpose in {"conversation", "reflection"}
    ]
    if len(turns) >= settings.max_round:
        return
    considered: set[str] = set()
    for item in turns:
        if item.id in state.speeches:
            considered.clear()
        if item.status == "applied" or item.id == turn.id:
            considered.add(item.character_id)
    candidates = [key for key in characters if key not in considered]
    recipient = consult or (candidates[0] if candidates else None)
    if recipient is None:
        return
    event = add_event(
        state,
        f"attention:{turn.id}",
        "consultation" if consult else "attention",
        turn.character_id,
        trigger.scope,
        turn.origin,
        trigger.content
        if consult
        else "Consider the saved conversation and choose your own response.",
        now,
        activity_id=trigger.activity_id,
        source=trigger.id,
    )
    enqueue(state, recipient, event, "conversation")


def refresh_speech(state: CollectiveState, speech: Speech, now: float) -> None:
    """Re-express unsent facts against the latest activity after a correction."""
    activity = state.activities.get(speech.activity_id or "")
    if activity is None or activity.version == speech.activity_version:
        return
    if any(
        part.speech_id == speech.id and part.attempted_at is not None
        for part in state.parts.values()
    ):
        return
    for key in [
        key for key, part in state.parts.items() if part.speech_id == speech.id
    ]:
        del state.parts[key]
    speech.activity_version = activity.version
    speech.body = None
    speech.status = "unrendered"
    speech.report = Report(
        achieved=speech.report.achieved if activity.status == "done" else [],
        findings=[*speech.report.findings, activity.last_result]
        if activity.last_result
        else speech.report.findings,
        evidence=speech.report.evidence,
        uncertainty=[
            *speech.report.uncertainty,
            f"Current state: {activity.status}. {activity.reason}",
        ],
        question=activity.question,
    )
    event = add_event(
        state,
        f"refresh:{speech.id}:{activity.version}",
        "report",
        speech.character_id,
        speech.scope,
        speech.origin,
        speech.report.model_dump_json(),
        now,
        activity.id,
    )
    enqueue(state, speech.character_id, event, "render", speech_id=speech.id)


def apply_work(
    state: CollectiveState,
    turn: Turn,
    result: WorkResult,
    characters: dict[str, Character],
    settings: CollectiveSettings,
    now: float,
) -> None:
    """Require evidence for each criterion and keep old results without old actions."""
    assert turn.context is not None
    activity = state.activities.get(turn.activity_id or "")
    if activity is None:
        if result.action != "propose":
            raise ValueError(
                "Unregistered reflection is read-only and may only propose"
            )
        if result.proposal is not None:
            if result.proposal.action != "start":
                raise ValueError("Reflection can propose only a new activity")
            activity = apply_change(state, turn, result.proposal, characters)
    else:
        if activity.version != turn.context.activity_versions.get(activity.id):
            turn.status = "applied"
            turn.error = (
                "Stale work retained as evidence; no actions or promises applied"
            )
            return
        if result.action == "propose":
            raise ValueError("An existing activity needs a continuation decision")
        if result.action == "done":
            if (
                not set(activity.criteria).issubset(result.evidence)
                or result.remaining
                or result.next_step
            ):
                raise ValueError(
                    "Completion requires evidence for every criterion and no remaining work"
                )
            if result.report is None:
                raise ValueError("Completion requires a report")
            activity.status = "done"
        elif result.action == "sleep":
            if result.wake_at is None or result.wake_at <= now or not result.reason:
                raise ValueError("Sleeping requires a future recheck time and reason")
            activity.status = "sleeping"
            activity.wake_at = result.wake_at
        elif result.action == "ask":
            if result.report is None or not result.report.question.strip():
                raise ValueError("Waiting requires a question to deliver")
            activity.status = "waiting"
            activity.question = result.report.question
        elif result.action == "blocked":
            if not result.reason or not result.next_step:
                raise ValueError("Blocked work needs a reason and resumption condition")
            activity.status = "blocked"
        else:
            if not result.next_step:
                raise ValueError("Continuing requires a next step")
            if result.action == "handoff":
                if (
                    result.recipient not in characters
                    or result.recipient == activity.owner
                ):
                    raise ValueError("Handoff requires a configured peer")
                if not result.reason or not result.remaining:
                    raise ValueError("Handoff requires its reason and remaining work")
                activity.owner = result.recipient
            activity.status = "ready"
        activity.version += 1
        activity.reason = result.reason
        activity.next_step = result.next_step
        activity.evidence = result.evidence
        activity.remaining = result.remaining
        activity.artifacts = result.artifacts
        activity.last_result = result.summary
    apply_memories(state, turn, result.memories, now)
    if result.report is not None:
        save_speech(
            state,
            turn,
            characters,
            settings,
            now,
            report=result.report,
            activity=activity,
        )
    turn.status = "applied"
