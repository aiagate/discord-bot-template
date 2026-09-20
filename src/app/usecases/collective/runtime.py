"""Independent conversation and serial work lanes with durable checkpoints."""

import asyncio
from pathlib import Path

from app.contracts.messages.collective import (
    Character,
    CharacterState,
    CollectiveSettings,
    Decision,
    Lane,
    Scope,
    Turn,
    WorkContext,
    WorkResult,
)
from app.contracts.ports.collective import (
    CodexWork,
    CollectiveStore,
    Conversation,
    HoldTurn,
    InputTooLarge,
    Workspaces,
)
from app.usecases.collective.context import build_context, input_attempt, reduce_context
from app.usecases.collective.lifecycle import (
    StaleDecision,
    add_event,
    apply_decision,
    apply_work,
    enqueue,
    next_character,
    refresh_speech,
    times_speech_allowed,
)


class Collective:
    """Coordinate one master's collective without making semantic decisions itself."""

    def __init__(
        self,
        store: CollectiveStore,
        characters: dict[str, Character],
        master: str,
        conversation: Conversation,
        codex: CodexWork,
        workspaces: Workspaces,
        root: Path,
        settings: CollectiveSettings,
    ) -> None:
        if not characters:
            raise ValueError("At least one character is required")
        self.store = store
        self.characters = characters
        self.master = master
        self.conversation = conversation
        self.codex = codex
        self.workspaces = workspaces
        self.root = root
        self.settings = settings

    async def validate_inputs(self, now: float) -> None:
        """Measure complete startup contexts and retain their capacity diagnostics."""
        limits = await self.conversation.limits()
        if limits.output_reserve > limits.output_tokens or limits.budget <= 0:
            raise ValueError("Output reservation exceeds the current model limits")
        for character_id in self.characters:
            snapshot = self.store.read()
            key = f"input-check:{character_id}:{now}"
            event = add_event(
                snapshot,
                key,
                "input_check",
                character_id,
                "times",
                key,
                "Startup input capacity check",
                now,
            )
            turn = enqueue(snapshot, character_id, event, "reflection")
            context = build_context(snapshot, turn, self.characters, self.master, now)
            while True:
                tokens = await self.conversation.count(context, None)
                attempt = input_attempt(context, limits, tokens)
                with self.store.transaction() as state:
                    add_event(
                        state,
                        f"{key}:{len(context.omissions)}",
                        "input_check",
                        character_id,
                        "times",
                        key,
                        attempt.model_dump_json(),
                        now,
                    )
                if tokens <= limits.budget:
                    break
                reduced = reduce_context(context)
                if reduced is None:
                    break
                context = reduced

    def receive(
        self,
        message_id: str,
        content: str,
        scope: Scope,
        now: float,
        character_id: str | None = None,
        source: str = "",
    ) -> bool:
        """Persist a normal master message once, with no command parsing required."""
        if character_id is not None and character_id not in self.characters:
            raise ValueError("Unknown character")
        with self.store.transaction() as state:
            key = f"discord:{message_id}"
            if key in state.events:
                return False
            selected = character_id or next_character(state, self.characters, scope)
            event = add_event(
                state, key, "message", "master", scope, key, content, now, source=source
            )
            enqueue(state, selected, event, "conversation")
            return True

    def schedule(self, now: float) -> None:
        """Coalesce overdue reflections and resume only recorded due conditions."""
        with self.store.transaction() as state:
            for character_id in self.characters:
                current = state.characters.setdefault(
                    character_id, CharacterState(id=character_id)
                )
                pending = any(
                    t.character_id == character_id
                    and t.purpose == "reflection"
                    and t.status in {"pending", "running", "retry"}
                    for t in state.turns.values()
                )
                if current.next_reflection <= now and not pending:
                    key = f"reflection:{character_id}:{current.next_reflection}"
                    event = add_event(
                        state,
                        key,
                        "reflection",
                        character_id,
                        "times",
                        key,
                        "Review memory, present circumstances and existing work; act only when useful.",
                        now,
                    )
                    enqueue(
                        state,
                        character_id,
                        event,
                        "reflection",
                        self.settings.reflection_lane,
                    )
                    current.next_reflection = now + self.settings.reflection_seconds
            for activity in state.activities.values():
                if (
                    activity.status == "sleeping"
                    and activity.wake_at is not None
                    and activity.wake_at <= now
                ):
                    activity.status = "ready"
                    activity.version += 1
                    activity.reason = (
                        f"Recorded recheck time reached: {activity.wake_at}"
                    )
                    activity.wake_at = None
                if activity.status != "ready":
                    continue
                if any(
                    t.activity_id == activity.id
                    and t.lane == "work"
                    and t.status in {"pending", "retry", "running"}
                    for t in state.turns.values()
                ):
                    continue
                if activity.runs >= self.settings.max_activity_runs:
                    activity.status = "blocked"
                    activity.reason = (
                        "Activity run budget reached; explicit resumption is required"
                    )
                    continue
                event = add_event(
                    state,
                    f"work:{activity.id}:{activity.version}",
                    "work_due",
                    activity.owner,
                    "times",
                    activity.source,
                    activity.next_step,
                    now,
                    activity_id=activity.id,
                )
                enqueue(state, activity.owner, event, "work", "work", activity.id)

    def _claim(self, lane: Lane, now: float) -> Turn | None:
        with self.store.transaction() as state:
            if any(
                t.lane == lane and t.status == "running" for t in state.turns.values()
            ):
                return None
            for turn in state.turns.values():
                if (
                    turn.lane != lane
                    or turn.status not in {"pending", "retry"}
                    or turn.next_at > now
                ):
                    continue
                if turn.purpose == "work":
                    activity = state.activities[turn.activity_id or ""]
                    if (
                        activity.status != "ready"
                        or activity.owner != turn.character_id
                    ):
                        turn.status = "applied"
                        turn.error = "Superseded before execution"
                        continue
                    activity.status = "running"
                    activity.runs += 1
                if turn.output is None:
                    turn.context = build_context(
                        state, turn, self.characters, self.master, now
                    )
                    turn.context.times_speech_allowed = times_speech_allowed(
                        state, turn, self.settings, now
                    )
                turn.status = "running"
                turn.attempts += 1
                return turn.model_copy(deep=True)
        return None

    async def _generate(self, turn: Turn) -> str:
        assert turn.context is not None
        context = turn.context
        speech = self.store.read().speeches.get(turn.speech_id or "")
        limits = await self.conversation.limits()
        if limits.output_reserve > limits.output_tokens or limits.budget <= 0:
            raise HoldTurn("Configured output reserve exceeds the current model limits")
        api_attempts = 0
        while True:
            tokens = await self.conversation.count(context, speech)
            with self.store.transaction() as state:
                saved = state.turns[turn.id]
                saved.context = context
                saved.input_attempts.append(input_attempt(context, limits, tokens))
            if tokens <= limits.budget:
                try:
                    if speech is not None:
                        body = await self.conversation.render(context, speech)
                        if not body.strip():
                            raise ValueError(
                                "The conversation model returned empty speech"
                            )
                        return body
                    return (await self.conversation.converse(context)).model_dump_json()
                except InputTooLarge:
                    api_attempts += 1
                    if api_attempts >= self.settings.max_attempts:
                        raise HoldTurn(
                            "Provider input-limit retry budget reached"
                        ) from None
            reduced = reduce_context(context)
            if reduced is None:
                raise HoldTurn(
                    f"Required context cannot fit: {tokens} tokens, budget {limits.budget}"
                )
            context = reduced

    def _save_output(self, turn: Turn, output: str, now: float) -> None:
        with self.store.transaction() as state:
            state.turns[turn.id].output = output
            add_event(
                state,
                f"result:{turn.id}"
                if turn.lane == "work"
                else f"result:{turn.id}:{turn.attempts}",
                "work_result" if turn.lane == "work" else "decision",
                turn.character_id,
                state.events[turn.trigger_id].scope,
                turn.origin,
                output,
                now,
                activity_id=turn.activity_id,
            )

    def _apply(self, turn_id: str, now: float) -> None:
        with self.store.transaction() as state:
            turn = state.turns[turn_id]
            if turn.status == "applied" or turn.output is None:
                return
            if turn.purpose == "render":
                speech = state.speeches[turn.speech_id or ""]
                if speech.status != "unrendered":
                    turn.status = "applied"
                    return
                activity = state.activities.get(speech.activity_id or "")
                if activity and activity.version != speech.activity_version:
                    refresh_speech(state, speech, now)
                    turn.status = "applied"
                    turn.error = "Report superseded by a newer activity version"
                    return
                speech.body = turn.output
                speech.status = "ready"
                event = state.events[f"speech:{speech.id}"]
                event.content = speech.body
                event.kind = "speech"
                turn.status = "applied"
            elif turn.lane == "work":
                apply_work(
                    state,
                    turn,
                    WorkResult.model_validate_json(turn.output),
                    self.characters,
                    self.settings,
                    now,
                )
            else:
                apply_decision(
                    state,
                    turn,
                    Decision.model_validate_json(turn.output),
                    self.characters,
                    self.settings,
                    now,
                )

    def _fail(self, turn_id: str, error: Exception, now: float) -> None:
        with self.store.transaction() as state:
            turn = state.turns[turn_id]
            if turn.status == "applied":
                return
            turn.error = f"{type(error).__name__}: {error}"
            turn.next_at = now + self.settings.retry_seconds * max(1, turn.attempts)
            if isinstance(error, StaleDecision):
                turn.output = None
                turn.context = None
            elif turn.output is not None and isinstance(error, (ValueError, KeyError)):
                turn.status = "held"
                if turn.activity_id:
                    activity = state.activities[turn.activity_id]
                    if activity.status == "running":
                        activity.status = "blocked"
                        activity.reason = turn.error
                return
            turn.status = (
                "held"
                if isinstance(error, HoldTurn)
                or turn.attempts >= self.settings.max_attempts
                else "retry"
            )
            if turn.lane == "work" and turn.activity_id:
                activity = state.activities[turn.activity_id]
                if activity.status == "running":
                    activity.status = "blocked" if turn.status == "held" else "ready"
                    activity.reason = turn.error
                    turn.recovery = True

    async def _interrupt_changed_work(self) -> None:
        state = self.store.read()
        for turn in state.turns.values():
            if (
                turn.lane != "work"
                or turn.status != "running"
                or not turn.activity_id
                or turn.context is None
            ):
                continue
            if (
                state.activities[turn.activity_id].version
                != turn.context.activity_versions[turn.activity_id]
            ):
                if await self.codex.interrupt(turn.id):
                    with self.store.transaction() as latest:
                        latest.turns[turn.id].status = "applied"
                        latest.turns[
                            turn.id
                        ].error = "Interrupted after a saved control or correction"

    async def conversation_step(self, now: float) -> bool:
        """Run one conversation, reflection, memory, or report expression turn."""
        turn = self._claim("conversation", now)
        if turn is None:
            return False
        try:
            async with asyncio.timeout(self.settings.turn_timeout):
                output = (
                    turn.output
                    if turn.output is not None
                    else await self._generate(turn)
                )
            self._save_output(turn, output, now)
            self._apply(turn.id, now)
            await self._interrupt_changed_work()
        except Exception as error:
            self._fail(turn.id, error, now)
        return True

    async def work_step(self, now: float) -> bool:
        """Run one Codex operation; its process tree must exit before another starts."""
        for pending in self.store.read().turns.values():
            if (
                pending.lane != "work"
                or pending.status != "retry"
                or pending.next_at > now
            ):
                continue
            output = pending.output or self.codex.saved_result(pending.execution)
            if output is not None:
                try:
                    with self.store.transaction() as state:
                        state.turns[pending.id].attempts += 1
                    self._save_output(pending, output, now)
                    self._apply(pending.id, now)
                except Exception as error:
                    self._fail(pending.id, error, now)
                return True
        turn = self._claim("work", now)
        if turn is None:
            return False
        assert turn.context is not None

        async def record(kind: str, value: str) -> None:
            with self.store.transaction() as state:
                state.turns[turn.id].execution[kind] = value

        try:
            if turn.output is None:
                snapshot = self.store.read()
                context = WorkContext(
                    context=turn.context,
                    run_id=turn.id,
                    workspace=self.root / "work" / turn.character_id,
                    references={},
                    activity=snapshot.activities.get(turn.activity_id or ""),
                    previous_results=[
                        e.content
                        for e in snapshot.events.values()
                        if e.kind == "work_result"
                        and e.activity_id == turn.activity_id
                        and e.actor == turn.character_id
                    ],
                    recovery=turn.recovery,
                    attempt=turn.attempts,
                )
                context = self.workspaces.prepare(context, snapshot)
                with self.store.transaction() as state:
                    state.characters.setdefault(
                        turn.character_id, CharacterState(id=turn.character_id)
                    ).projection = turn.context.memory_versions
                async with asyncio.timeout(self.settings.turn_timeout):
                    result = await self.codex.run_codex(context, record)
                self._save_output(turn, result.model_dump_json(), now)
            self._apply(turn.id, now)
        except Exception as error:
            if await self.codex.interrupt(turn.id):
                self._fail(turn.id, error, now)
            else:
                with self.store.transaction() as state:
                    state.turns[
                        turn.id
                    ].error = "Process termination is unconfirmed; work lane retained"
        return True

    async def recover(self, now: float) -> None:
        """Apply saved outputs and inspect incomplete executions before reopening work."""
        for turn in self.store.read().turns.values():
            if turn.status != "running":
                continue
            if turn.lane == "work" and not await self.codex.recover(turn.execution):
                continue
            if turn.lane == "work" and turn.output is None:
                output = self.codex.saved_result(turn.execution)
                if output is not None:
                    self._save_output(turn, output, now)
                    turn.output = output
            if turn.output is not None:
                try:
                    self._apply(turn.id, now)
                except Exception as error:
                    self._fail(turn.id, error, now)
                continue
            with self.store.transaction() as state:
                saved = state.turns[turn.id]
                saved.status = "retry"
                saved.next_at = now
                saved.recovery = saved.lane == "work"
                if saved.activity_id:
                    activity = state.activities[saved.activity_id]
                    if activity.status == "running":
                        activity.status = "ready"
                        activity.reason = "Previous outcome unknown; inspect actual state before continuing"

    async def stop(self, activity_id: str, reason: str, now: float) -> None:
        """Administrative stop remains available when model input is held."""
        with self.store.transaction() as state:
            activity = state.activities[activity_id]
            if activity.status == "done":
                raise ValueError("Completed activity cannot be stopped")
            activity.status = "stopped"
            activity.version += 1
            activity.reason = reason
            add_event(
                state,
                f"stop:{activity_id}:{activity.version}",
                "stop",
                "master",
                "master",
                activity.source,
                reason,
                now,
                activity_id=activity_id,
            )
        await self._interrupt_changed_work()
