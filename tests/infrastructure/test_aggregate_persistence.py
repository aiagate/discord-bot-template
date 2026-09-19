"""Repository contracts for complete parent/child snapshots and shared transactions."""

from dataclasses import replace
from datetime import UTC
from unittest.mock import patch

import pytest
from flow_res import Err, is_err, is_ok
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from app.domain.aggregates.user import User
from app.domain.repositories import RepositoryErrorType
from app.domain.value_objects import DisplayName, Email, UserId
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork
from tests.helpers.aggregate_persistence import (
    IOrderRepository,
    Order,
    OrderLine,
    OrderLineORM,
    OrderRepository,
    PersistenceModel,
    order_from_orm,
    order_to_orm,
)


@pytest.fixture
async def aggregate_uow(
    database_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> SQLAlchemyUnitOfWork:
    for attribute in ("_domain_to_orm", "_to_orm", "_from_orm"):
        monkeypatch.setattr(
            ORMMappingRegistry, attribute, getattr(ORMMappingRegistry, attribute).copy()
        )
    from tests.helpers.aggregate_persistence import OrderORM

    ORMMappingRegistry.register(Order, OrderORM, order_to_orm, order_from_orm)
    async with database_engine.begin() as connection:
        await connection.run_sync(PersistenceModel.metadata.create_all)
    return SQLAlchemyUnitOfWork(
        session_factory, repository_factories={IOrderRepository: OrderRepository}
    )


def new_user() -> User:
    return User.register(DisplayName("Writer"), Email("writer@example.com"))


def new_order(id: str = "order") -> Order:
    return Order(id, (OrderLine(f"{id}-a", 1), OrderLine(f"{id}-b", 2)))


async def persist(uow: SQLAlchemyUnitOfWork, order: Order) -> Order:
    async with uow:
        saved = (await uow.GetCustomRepository(IOrderRepository).add(order)).unwrap()
        assert is_ok(await uow.commit())
        return saved


@pytest.mark.anyio
async def test_full_snapshot_roundtrip_and_child_changes(
    aggregate_uow: SQLAlchemyUnitOfWork,
) -> None:
    assert not set(PersistenceModel.metadata.tables) & set(SQLModel.metadata.tables)
    saved = await persist(aggregate_uow, new_order())
    assert saved.version.to_primitive() == 0

    async with aggregate_uow:
        loaded = (
            await aggregate_uow.GetCustomRepository(IOrderRepository).get_by_id(
                saved.id
            )
        ).unwrap()
    assert loaded.lines == saved.lines
    assert loaded.id == saved.id
    assert loaded.created_at.replace(tzinfo=UTC) == saved.created_at
    assert loaded.updated_at.replace(tzinfo=UTC) == saved.updated_at

    changed = replace(loaded, lines=(OrderLine("order-a", 7), OrderLine("order-c", 3)))
    async with aggregate_uow:
        updated = (
            await aggregate_uow.GetCustomRepository(IOrderRepository).update(changed)
        ).unwrap()
        assert updated.version.to_primitive() == 1
        assert updated.created_at == loaded.created_at
        assert updated.updated_at.replace(tzinfo=UTC) > loaded.updated_at.replace(
            tzinfo=UTC
        )
        assert is_ok(await aggregate_uow.commit())

    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        reloaded = (await repository.get_by_id(saved.id)).unwrap()
        assert reloaded.lines == changed.lines
        emptied = (await repository.update(replace(reloaded, lines=()))).unwrap()
        assert emptied.version.to_primitive() == 2
        assert is_ok(await aggregate_uow.commit())

    async with aggregate_uow:
        final = (
            await aggregate_uow.GetCustomRepository(IOrderRepository).get_by_id(
                saved.id
            )
        ).unwrap()
    assert final.lines == ()


@pytest.mark.anyio
async def test_identical_snapshot_still_increments_version(
    aggregate_uow: SQLAlchemyUnitOfWork,
) -> None:
    saved = await persist(aggregate_uow, new_order())
    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        first = (await repository.update(saved)).unwrap()
        second = (await repository.update(first)).unwrap()
        assert first.version.to_primitive() == 1
        assert second.version.to_primitive() == 2
        assert second.lines == saved.lines
        assert second.created_at == saved.created_at
        assert is_ok(await aggregate_uow.commit())


@pytest.mark.anyio
async def test_delete_cascades_only_to_owned_children(
    aggregate_uow: SQLAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deleted = await persist(aggregate_uow, new_order())
    retained = await persist(aggregate_uow, new_order("retained"))
    async with aggregate_uow:
        assert is_ok(
            await aggregate_uow.GetCustomRepository(IOrderRepository).delete(deleted)
        )
        assert is_ok(await aggregate_uow.commit())
    async with session_factory() as session:
        children = (await session.execute(select(OrderLineORM))).scalars().all()
        assert {child.id for child in children} == {line.id for line in retained.lines}
    async with aggregate_uow:
        assert (
            await aggregate_uow.GetCustomRepository(IOrderRepository).get_by_id(
                retained.id
            )
        ).unwrap().lines == retained.lines


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize("missing", [False, True])
async def test_precheck_rejection_preserves_unrelated_writes(
    aggregate_uow: SQLAlchemyUnitOfWork, operation: str, missing: bool
) -> None:
    stale = await persist(aggregate_uow, new_order())
    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        if missing:
            assert is_ok(await repository.delete(stale))
        else:
            assert is_ok(await repository.update(stale))
        assert is_ok(await aggregate_uow.commit())

    user = new_user()
    async with aggregate_uow:
        assert is_ok(await aggregate_uow.GetRepository(User).add(user))
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        result = await (
            repository.update(stale)
            if operation == "update"
            else repository.delete(stale)
        )
        assert isinstance(result, Err)
        assert result.error.type == (
            RepositoryErrorType.NOT_FOUND
            if missing
            else RepositoryErrorType.VERSION_CONFLICT
        )
        assert is_ok(await aggregate_uow.commit())
    async with aggregate_uow:
        assert is_ok(await aggregate_uow.GetRepository(User, UserId).get_by_id(user.id))


@pytest.mark.anyio
@pytest.mark.parametrize("loser_operation", ["update", "delete"])
@pytest.mark.parametrize("winner_operation", ["update", "delete"])
async def test_flush_detects_real_race_and_rolls_back_children(
    aggregate_uow: SQLAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
    loser_operation: str,
    winner_operation: str,
) -> None:
    saved = await persist(aggregate_uow, new_order())
    winner_snapshot = replace(
        saved, lines=(OrderLine("order-a", 8), OrderLine("winner-new", 1))
    )
    loser_snapshot = replace(
        saved, lines=(OrderLine("order-b", 9), OrderLine("loser-new", 1))
    )
    competing_uow = SQLAlchemyUnitOfWork(session_factory)
    async with aggregate_uow:
        assert aggregate_uow._session is not None
        session = aggregate_uow._session
        flush = session.flush

        async def compete_then_flush() -> None:
            async with competing_uow:
                winner = competing_uow.GetRepository(Order, str)
                result = await (
                    winner.update(winner_snapshot)
                    if winner_operation == "update"
                    else winner.delete(saved)
                )
                assert not isinstance(result, Err)
                assert is_ok(await competing_uow.commit())
            await flush()

        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        with patch.object(session, "flush", side_effect=compete_then_flush):
            result = await (
                repository.update(loser_snapshot)
                if loser_operation == "update"
                else repository.delete(saved)
            )
        assert isinstance(result, Err)
        assert result.error.type == (
            RepositoryErrorType.VERSION_CONFLICT
            if winner_operation == "update"
            else RepositoryErrorType.NOT_FOUND
        )
        assert is_err(await aggregate_uow.commit())
        await aggregate_uow.rollback()
        assert is_err(await aggregate_uow.commit())

    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        if winner_operation == "update":
            loaded = (await repository.get_by_id(saved.id)).unwrap()
            assert loaded.lines == winner_snapshot.lines
            assert loaded.version.to_primitive() == 1
        else:
            assert is_err(await repository.get_by_id(saved.id))
        assert is_ok(await aggregate_uow.commit())
    async with session_factory() as session:
        children = (await session.execute(select(OrderLineORM))).scalars().all()
        expected = winner_snapshot.lines if winner_operation == "update" else ()
        assert {child.id: child.quantity for child in children} == {
            line.id: line.quantity for line in expected
        }


@pytest.mark.anyio
@pytest.mark.parametrize("direct_custom_write", [False, True])
async def test_child_constraint_failure_invalidates_entire_scope(
    aggregate_uow: SQLAlchemyUnitOfWork, direct_custom_write: bool
) -> None:
    saved = await persist(aggregate_uow, new_order())
    user = new_user()
    async with aggregate_uow:
        assert is_ok(await aggregate_uow.GetRepository(User).add(user))
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        assert is_ok(await repository.add(new_order("sibling")))
        if direct_custom_write:
            failed = await repository.add_with_direct_flush(
                Order("invalid", (OrderLine("invalid-child", 0),))
            )
        else:
            failed = await repository.update(
                replace(
                    saved,
                    lines=(OrderLine("order-a", 9), OrderLine("invalid-child", 0)),
                )
            )
        assert isinstance(failed, Err)
        assert is_err(await aggregate_uow.commit())

    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        assert await repository.count() == 1
        loaded = (await repository.get_by_id(saved.id)).unwrap()
        assert loaded.lines == saved.lines
        assert loaded.version == saved.version
        assert is_err(
            await aggregate_uow.GetRepository(User, UserId).get_by_id(user.id)
        )
        assert is_ok(await aggregate_uow.commit())


@pytest.mark.anyio
@pytest.mark.parametrize("exit_kind", ["commit", "uncommitted", "exception"])
async def test_generic_and_custom_repositories_share_transaction(
    aggregate_uow: SQLAlchemyUnitOfWork, exit_kind: str
) -> None:
    user = new_user()
    try:
        async with aggregate_uow:
            assert is_ok(await aggregate_uow.GetRepository(User).add(user))
            custom = aggregate_uow.GetCustomRepository(IOrderRepository)
            assert is_ok(await custom.add(new_order()))
            assert await custom.count() == 1
            if exit_kind == "commit":
                assert is_ok(await aggregate_uow.commit())
            elif exit_kind == "exception":
                raise ValueError("cancel operation")
    except ValueError:
        assert exit_kind == "exception"

    async with aggregate_uow:
        result = await aggregate_uow.GetRepository(User, UserId).get_by_id(user.id)
        count = await aggregate_uow.GetCustomRepository(IOrderRepository).count()
        assert is_ok(result) == (exit_kind == "commit")
        assert count == (1 if exit_kind == "commit" else 0)


@pytest.mark.anyio
async def test_custom_repository_lifecycle_and_explicit_rollback(
    aggregate_uow: SQLAlchemyUnitOfWork,
) -> None:
    with pytest.raises(RuntimeError, match="session not initialized"):
        aggregate_uow.GetCustomRepository(IOrderRepository)
    async with aggregate_uow:
        first = aggregate_uow.GetCustomRepository(IOrderRepository)
        assert first is aggregate_uow.GetCustomRepository(IOrderRepository)
        with pytest.raises(ValueError, match="No repository factory"):
            aggregate_uow.GetCustomRepository(OrderRepository)
        with pytest.raises(RuntimeError, match="already has an active scope"):
            await aggregate_uow.__aenter__()
        assert is_ok(await first.add(new_order()))
        await aggregate_uow.rollback()
        assert await first.count() == 0
        assert is_ok(await first.add(new_order("after-rollback")))
        assert is_ok(await aggregate_uow.commit())
    with pytest.raises(RuntimeError, match="session not initialized"):
        aggregate_uow.GetCustomRepository(IOrderRepository)
    async with aggregate_uow:
        following = aggregate_uow.GetCustomRepository(IOrderRepository)
        assert following is not first
        assert await following.count() == 1


@pytest.mark.anyio
async def test_deleted_row_is_not_reinserted_by_merge(
    aggregate_uow: SQLAlchemyUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    saved = await persist(aggregate_uow, new_order())
    async with aggregate_uow:
        assert aggregate_uow._session is not None
        session = aggregate_uow._session
        merge = session.merge

        async def delete_then_merge(instance: SQLModel, *, load: bool) -> SQLModel:
            async with SQLAlchemyUnitOfWork(session_factory) as competing:
                assert is_ok(await competing.GetRepository(Order).delete(saved))
                assert is_ok(await competing.commit())
            return await merge(instance, load=load)

        with patch.object(session, "merge", side_effect=delete_then_merge):
            result = await aggregate_uow.GetCustomRepository(IOrderRepository).update(
                saved
            )
        assert is_err(result)
        assert result.error.type is RepositoryErrorType.NOT_FOUND
        assert is_err(await aggregate_uow.commit())
    async with aggregate_uow:
        assert await aggregate_uow.GetCustomRepository(IOrderRepository).count() == 0


@pytest.mark.anyio
async def test_update_preserves_persisted_creation_time(
    aggregate_uow: SQLAlchemyUnitOfWork,
) -> None:
    saved = await persist(aggregate_uow, new_order())
    changed = replace(saved, created_at=saved.created_at.replace(year=2000))
    async with aggregate_uow:
        result = (
            await aggregate_uow.GetCustomRepository(IOrderRepository).update(changed)
        ).unwrap()
        assert result.created_at == saved.created_at
        assert result.updated_at > saved.updated_at
        assert is_ok(await aggregate_uow.commit())


@pytest.mark.anyio
async def test_repositories_cannot_reopen_a_closed_scope(
    aggregate_uow: SQLAlchemyUnitOfWork,
) -> None:
    async with aggregate_uow:
        old_generic = aggregate_uow.GetRepository(User, UserId)
        old_custom = aggregate_uow.GetCustomRepository(IOrderRepository)
    for active_scope in (False, True):
        if active_scope:
            await aggregate_uow.__aenter__()
        try:
            result = await old_generic.add(new_user())
            assert is_err(result)
            assert result.error.type is RepositoryErrorType.UNEXPECTED
            with pytest.raises(InvalidRequestError, match="permanently closed"):
                await old_custom.count()
            if active_scope:
                assert is_ok(await aggregate_uow.GetRepository(User).add(new_user()))
                assert is_ok(
                    await aggregate_uow.GetCustomRepository(IOrderRepository).add(
                        new_order()
                    )
                )
                assert is_ok(await aggregate_uow.commit())
        finally:
            if active_scope:
                await aggregate_uow.__aexit__(None, None, None)
    async with aggregate_uow:
        assert await aggregate_uow.GetCustomRepository(IOrderRepository).count() == 1


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["add", "update"])
async def test_restore_failure_after_flush_rolls_back_entire_scope(
    aggregate_uow: SQLAlchemyUnitOfWork, operation: str
) -> None:
    from tests.helpers.aggregate_persistence import OrderORM

    saved = await persist(aggregate_uow, new_order())
    user = new_user()

    def reject_restore(row: SQLModel) -> Order:
        raise ValueError("invalid restored snapshot")

    async with aggregate_uow:
        assert is_ok(await aggregate_uow.GetRepository(User).add(user))
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        with patch.dict(ORMMappingRegistry._from_orm, {OrderORM: reject_restore}):
            result = await (
                repository.add(new_order("rejected"))
                if operation == "add"
                else repository.update(
                    replace(saved, lines=(OrderLine("replacement", 9),))
                )
            )
        assert is_err(result)
        assert result.error.type is RepositoryErrorType.UNEXPECTED
        assert result.error.message == "invalid restored snapshot"
        assert is_err(await aggregate_uow.commit())
    async with aggregate_uow:
        repository = aggregate_uow.GetCustomRepository(IOrderRepository)
        assert await repository.count() == 1
        restored = (await repository.get_by_id(saved.id)).unwrap()
        assert restored.version == saved.version
        assert restored.lines == saved.lines
        assert is_err(
            await aggregate_uow.GetRepository(User, UserId).get_by_id(user.id)
        )
