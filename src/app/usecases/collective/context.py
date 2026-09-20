"""Build complete contexts and remove only whole, connected source groups."""

import json

from app.contracts.messages.collective import (
    Character,
    CharacterContext,
    CollectiveState,
    ContextItem,
    InputAttempt,
    ModelLimits,
    Omission,
    Turn,
)


def build_context(
    state: CollectiveState,
    turn: Turn,
    characters: dict[str, Character],
    master: str,
    now: float,
) -> CharacterContext:
    """Include all owned memory and configured conversation scopes by default."""
    trigger = state.events[turn.trigger_id]
    items: list[ContextItem] = []
    relevant = {turn.activity_id} if turn.activity_id else set()
    relevant.update(
        activity.id
        for activity in state.activities.values()
        if activity.status not in {"done", "stopped"}
    )
    groups: dict[str, list[str]] = {}
    required_sources = {turn.trigger_id}
    for activity in state.activities.values():
        if activity.id in relevant:
            required_sources.update((activity.source, activity.instruction_source))
    for event in state.events.values():
        if event.scope not in {"master", "times"}:
            continue
        if event.kind in {"decision", "attention", "input_check"}:
            continue
        if event.kind not in {
            "message",
            "speech",
            "stop",
            "consultation",
        } and event.actor not in {"master", turn.character_id}:
            continue
        group = event.activity_id or event.origin
        groups.setdefault(group, []).append(event.id)
    for group, ids in groups.items():
        pending_sources = {
            s.event_id
            for s in state.memory_sources.values()
            if s.owner in {"master", turn.character_id} and s.status == "pending"
        }
        required = bool(required_sources.intersection(ids)) or group in relevant
        events = []
        for event_id in ids:
            event = state.events[event_id]
            value = event.model_dump(mode="json")
            speech = state.speeches.get(event.id.removeprefix("speech:"))
            if speech is not None:
                value["delivered"] = speech.status == "sent"
            events.append(value)
        items.append(
            ContextItem(
                id=f"history:{group}",
                priority="required"
                if required
                else "high"
                if pending_sources.intersection(ids)
                else "low",
                sources=ids,
                content=json.dumps(events, ensure_ascii=False),
            )
        )
    memory_versions: dict[str, int] = {}
    for key, memory in state.memories.items():
        if memory.owner not in {"master", turn.character_id}:
            continue
        memory_versions[key] = memory.version
        if memory.deleted:
            continue
        required = turn.trigger_id in memory.sources
        items.append(
            ContextItem(
                id=f"memory:{key}",
                priority="required" if required else "high",
                sources=memory.sources,
                content=memory.model_dump_json(),
            )
        )
    for activity in state.activities.values():
        items.append(
            ContextItem(
                id=f"activity:{activity.id}",
                priority="required" if activity.id in relevant else "low",
                sources=[activity.source],
                content=activity.model_dump_json(),
            )
        )
    return CharacterContext(
        character=characters[turn.character_id],
        master=master,
        peers={
            key: value.public_profile
            for key, value in characters.items()
            if key != turn.character_id
        },
        scope=trigger.scope,
        purpose=turn.purpose,
        trigger=trigger,
        now=now,
        items=items,
        activity_versions={
            key: value.version for key, value in state.activities.items()
        },
        memory_versions=memory_versions,
        event_sequence=max(
            (event.sequence for event in state.events.values()), default=0
        ),
    )


def reduce_context(context: CharacterContext) -> CharacterContext | None:
    """Remove the oldest lowest-priority connected group without cutting meaning."""
    for priority in ("low", "high"):
        for item in context.items:
            if item.priority != priority:
                continue
            selected = {item.id}
            sources = set(item.sources)
            changed = True
            while changed:
                changed = False
                for other in context.items:
                    if other.id not in selected and sources.intersection(other.sources):
                        selected.add(other.id)
                        sources.update(other.sources)
                        changed = True
            if any(
                i.priority == "required" and i.id in selected for i in context.items
            ):
                continue
            if priority == "low" and any(
                i.priority == "high" and i.id in selected for i in context.items
            ):
                continue
            return context.model_copy(
                update={
                    "items": [i for i in context.items if i.id not in selected],
                    "omissions": [
                        *context.omissions,
                        Omission(
                            source_ids=sorted(sources),
                            reason=f"input budget: {priority} priority",
                        ),
                    ],
                }
            )
    return None


def input_attempt(
    context: CharacterContext, limits: ModelLimits, tokens: int
) -> InputAttempt:
    """Record exact total tokens and section bytes without claiming additive counts."""
    return InputAttempt(
        limits=limits,
        model=limits.model,
        budget=limits.budget,
        tokens=tokens,
        remaining=limits.budget - tokens,
        sections={
            "identity_bytes": len(context.character.model_dump_json().encode()),
            "policy_bytes": len(context.master.encode()),
            "items_bytes": sum(len(item.content.encode()) for item in context.items),
            "context_bytes": len(context.model_dump_json().encode()),
        },
        included=[item.id for item in context.items],
        omissions=context.omissions,
    )
