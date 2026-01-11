"""Generic Result type, inspired by Rust's Result type."""

from collections.abc import Awaitable, Callable, Coroutine, Generator, Sequence
from dataclasses import dataclass
from functools import wraps
from typing import Any, Never, TypeVar, overload

from typing_extensions import TypeIs

T = TypeVar("T")  # Success type
E = TypeVar("E", bound=Exception)  # Error type
U = TypeVar("U")  # Success type for map/and_then


@dataclass(frozen=True)
class AggregateErr[E](Exception):
    """
    Represents multiple errors collected during a validation process.

    Used primarily with combine_all to collect all validation errors
    so users can see all issues at once, rather than one at a time.
    """

    exceptions: list[E]

    def __str__(self) -> str:
        """Return a string representation of the aggregate error."""
        return f"Multiple errors occurred ({len(self.exceptions)}): {self.exceptions}"


@dataclass(frozen=True)
class Ok[T]:
    """Represents a successful result."""

    value: T

    def map[V](self, f: Callable[[T], V]) -> "Ok[V]":
        """
        Transform the Ok value using the provided function.

        Args:
            f: Function to apply to the Ok value (T -> V)

        Returns:
            Ok[V] containing the transformed value

        Example:
            Ok(5).map(lambda x: x * 2)  # Returns Ok(10)
        """
        return Ok(f(self.value))

    def and_then[V, F: Exception](
        self, f: Callable[[T], "Result[V, F]"]
    ) -> "Result[V, F]":
        """
        Apply a function that returns a Result, flattening the nested Result.

        This is the monadic bind operation (flatMap in some languages).
        Enables chaining operations that may fail.

        Args:
            f: Function that takes the Ok value and returns a new Result (T -> Result[V, F])

        Returns:
            Result[V, F] - The result of applying the function

        Example:
            Ok(5).and_then(lambda x: Ok(x * 2))  # Returns Ok(10)
            Ok(5).and_then(lambda x: Err(Exception("failed")))  # Returns Err(Exception("failed"))
        """
        return f(self.value)

    def unwrap(self) -> T:
        """
        Return the Ok value.

        Returns:
            The wrapped value
        """
        return self.value

    def expect(self, msg: str) -> T:
        """
        Return the value.

        Compatible with Err.expect signature to allow usage without type guards,
        but requires a message explaining why success is expected.

        Args:
            msg: Message explaining why this Result is expected to be Ok (for consistency)

        Returns:
            The wrapped value
        """
        return self.value

    def map_err[F: Exception](self, f: Callable[[Any], F]) -> "Ok[T]":
        """
        Pass through the Ok value unchanged.

        Args:
            f: Function to map error (ignored for Ok).

        Returns:
            Self (unchanged Ok value).
        """
        return self


@dataclass(frozen=True)
class Err[E]:
    """Represents a failure result."""

    error: E

    def map[V](self, f: Callable[[Any], Any]) -> "Err[E]":
        """
        Pass through the error unchanged (Railway-oriented programming pattern).

        Args:
            f: Function that would be applied (ignored for Err)

        Returns:
            Self (unchanged Err)
        """
        return self

    def and_then[V, F: Exception](self, f: Callable[[Any], "Result[V, F]"]) -> "Err[E]":
        """
        Pass through the error unchanged (Railway-oriented programming pattern).

        Since this is an Err, the function is not called and the error propagates.

        Args:
            f: Function that would be applied (ignored for Err)

        Returns:
            Self (unchanged Err)

        Example:
            Err(Exception("error")).and_then(lambda x: Ok(x * 2))  # Returns Err(Exception("error"))
        """
        return self

    def expect(self, msg: str) -> Never:
        """
        Raise an exception with the provided message.

        Used when you want to assert that this Result should be Ok.
        Requires a message explaining why the Result was expected to be Ok.

        Args:
            msg: Message explaining why this was expected to be Ok

        Raises:
            RuntimeError: Always raised with the provided message and underlying error

        Example:
            result.expect("User should exist in database")
        """
        if isinstance(self.error, Exception):
            raise RuntimeError(f"{msg}: {self.error}") from self.error
        raise RuntimeError(f"{msg}: {self.error}")

    def map_err[F: Exception](self, f: Callable[[E], F]) -> "Err[F]":
        """
        Transform the Err value using the provided function.

        Args:
            f: Function to apply to the Err value (E -> F).

        Returns:
            Err[F] containing the transformed error.
        """
        return Err(f(self.error))

    def unwrap(self) -> Never:
        """
        Raise the underlying error.

        This ensures that unwrap() can be called on Result (Ok | Err).
        """
        if isinstance(self.error, Exception):
            raise self.error
        raise RuntimeError(f"Unwrap failed: {self.error}")

    def unwrap_or[T](self, default: T) -> T:
        """
        Return the default value.

        Args:
            default: Value to return.

        Returns:
            The default value.
        """
        return default


Result = Ok[T] | Err[E]


def is_ok[T, E: Exception](result: Result[T, E]) -> TypeIs[Ok[T]]:
    """
    Return true if the result is ok.

    Uses TypeIs for bidirectional type narrowing - when this returns False,
    the type checker knows the result must be Err.
    """
    return isinstance(result, Ok)


def is_err[T, E: Exception](result: Result[T, E]) -> TypeIs[Err[E]]:
    """
    Return true if the result is an error.

    Uses TypeIs for bidirectional type narrowing - when this returns False,
    the type checker knows the result must be Ok.
    """
    return isinstance(result, Err)


def safe[T](func: Callable[..., T]) -> Callable[..., Result[T, Exception]]:
    """
    Decorator to convert a function that raises exceptions into one that returns a Result.

    This is inspired by the @safe decorator from dry-python/returns.
    It wraps any exceptions raised by the decorated function into an Err.

    Args:
        func: Function that may raise exceptions

    Returns:
        A wrapped function that returns Result[T, Exception] instead of raising

    Example:
        @safe
        def risky_operation(x: int) -> int:
            if x < 0:
                raise ValueError("Negative number")
            return x * 2

        result = risky_operation(-5)  # Returns Err(ValueError("Negative number"))
        result = risky_operation(5)   # Returns Ok(10)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Result[T, Exception]:
        try:
            return Ok(func(*args, **kwargs))
        except Exception as e:
            return Err(e)

    return wrapper


@overload
def combine[E: Exception](results: tuple[()]) -> Result[tuple[()], E]: ...


@overload
def combine[T1, E: Exception](
    results: tuple[Result[T1, E]],
) -> Result[tuple[T1], E]: ...


@overload
def combine[T1, T2, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E]],
) -> Result[tuple[T1, T2], E]: ...


@overload
def combine[T1, T2, T3, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E], Result[T3, E]],
) -> Result[tuple[T1, T2, T3], E]: ...


@overload
def combine[T1, T2, T3, T4, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E], Result[T3, E], Result[T4, E]],
) -> Result[tuple[T1, T2, T3, T4], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, E: Exception](
    results: tuple[
        Result[T1, E], Result[T2, E], Result[T3, E], Result[T4, E], Result[T5, E]
    ],
) -> Result[tuple[T1, T2, T3, T4, T5], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, T6, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, T6, T7, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, T6, T7, T8, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, T6, T7, T8, T9, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
        Result[T9, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9], E]: ...


@overload
def combine[T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
        Result[T9, E],
        Result[T10, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9, T10], E]: ...


def combine[T, E: Exception](
    results: Sequence[Result[T, E]],
) -> Result[tuple[T, ...], E]:
    """
    Aggregates a sequence of Result objects.

    If all results are Ok, returns an Ok containing a tuple of all success values.
    If any result is an Err, returns the first Err encountered.

    Args:
        results: A sequence of Result objects.

    Returns:
        A single Result object. Ok(tuple of success values) or the first Err.

    Examples:
        Heterogeneous types (use tuple):
        >>> user_id: Result[int, Exception] = Ok(123)
        >>> email: Result[str, Exception] = Ok("user@example.com")
        >>> combine((user_id, email))
        Ok((123, "user@example.com"))

        Homogeneous types (use list or tuple):
        >>> results = [Ok(1), Ok(2), Ok(3)]
        >>> combine(results)
        Ok((1, 2, 3))

        Error handling (first error returned):
        >>> results = [Ok(1), Err(Exception("error")), Ok(3)]
        >>> combine(results)
        Err(Exception("error"))
    """
    values: list[T] = []
    for r in results:
        if is_err(r):
            return r  # Return the first error found
        values.append(r.unwrap())
    return Ok(tuple(values))


@overload
def combine_all[T1, E: Exception](
    results: tuple[Result[T1, E]],
) -> Result[tuple[T1], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E]],
) -> Result[tuple[T1, T2], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E], Result[T3, E]],
) -> Result[tuple[T1, T2, T3], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, E: Exception](
    results: tuple[Result[T1, E], Result[T2, E], Result[T3, E], Result[T4, E]],
) -> Result[tuple[T1, T2, T3, T4], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, E: Exception](
    results: tuple[
        Result[T1, E], Result[T2, E], Result[T3, E], Result[T4, E], Result[T5, E]
    ],
) -> Result[tuple[T1, T2, T3, T4, T5], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, T6, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, T6, T7, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, T6, T7, T8, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, T6, T7, T8, T9, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
        Result[T9, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9], AggregateErr[E]]: ...


@overload
def combine_all[T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, E: Exception](
    results: tuple[
        Result[T1, E],
        Result[T2, E],
        Result[T3, E],
        Result[T4, E],
        Result[T5, E],
        Result[T6, E],
        Result[T7, E],
        Result[T8, E],
        Result[T9, E],
        Result[T10, E],
    ],
) -> Result[tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9, T10], AggregateErr[E]]: ...


def combine_all[E: Exception](
    results: Sequence[Result[Any, E]],
) -> Result[tuple[Any, ...], AggregateErr[E]]:
    """
    Aggregates a tuple of Results, collecting all errors.

    If all results are Ok, returns an Ok containing a tuple of all success values.
    If any result is an Err, returns an Err containing an AggregateErr with all errors.

    This is a "fail complete" strategy - useful for validation where you want to show
    all errors to the user at once, rather than one at a time.

    Args:
        results: A tuple of Result objects.

    Returns:
        Ok(tuple of success values) if all succeed,
        or Err(AggregateErr(list of errors)) if any fail.

    Example:
        >>> from app.core.result import combine_all, Ok, Err
        >>> results = (Ok(1), Err(Exception("error1")), Ok(3), Err(Exception("error2")))
        >>> combined = combine_all(results)
        >>> # Returns Err(AggregateErr([Exception("error1"), Exception("error2")]))
    """
    values: list[Any] = []
    errors: list[E] = []

    for r in results:
        if is_err(r):
            errors.append(r.error)
        else:
            values.append(r.unwrap())

    if errors:
        return Err(AggregateErr(errors))

    return Ok(tuple(values))


class ResultAwaitable[T, E: Exception]:
    """
    Awaitable wrapper for Result that enables method chaining before await.

    This allows elegant syntax like:
        message = await Mediator.send_async(query).map(...).unwrap()
    """

    def __init__(self, coro: Coroutine[Any, Any, Result[T, E]]) -> None:
        """
        Initialize with a coroutine that returns a Result.

        Args:
            coro: Coroutine that will return Result[T, E]
        """
        self._coro = coro

    def __await__(self) -> Generator[Any, None, Result[T, E]]:
        """Make this object awaitable, returning the underlying Result."""
        return self._coro.__await__()

    def map(self, f: Callable[[T], U]) -> "ResultAwaitable[U, E]":
        """
        Transform the Ok value using the provided function.

        This method chains onto the coroutine, creating a new coroutine that:
        1. Awaits the current Result
        2. Applies .map() to transform the value
        3. Returns the transformed Result

        Args:
            f: Function to apply to the Ok value (T -> U)

        Returns:
            ResultAwaitable[U, E] wrapping the transformed result

        Example:
            user_id = await Mediator.send_async(cmd).map(lambda v: v.user_id)
        """

        async def mapped() -> Result[U, E]:
            _result: Result[T, E] = await self
            return _result.map(f)

        return ResultAwaitable(mapped())

    def and_then(
        self, f: Callable[[T], Awaitable[Result[U, E]]]
    ) -> "ResultAwaitable[U, E]":
        """
        Apply an async function that returns a Result, flattening the nested Result.

        This enables chaining async operations that may fail.

        Args:
            f: Async function that takes the Ok value and returns a new Result
               (T -> Awaitable[Result[U, E]])

        Returns:
            ResultAwaitable[U, E] wrapping the result of applying the function

        Example:
            await (
                Mediator.send_async(create_cmd)
                .and_then(lambda result: Mediator.send_async(GetQuery(result.id)))
                .map(lambda value: format_message(value))
                .unwrap()
            )
        """

        async def chained() -> Result[U, E]:
            _result: Result[T, E] = await self
            match _result:
                case Ok(value):
                    return await f(value)
                case Err():
                    return _result

        return ResultAwaitable(chained())

    def unwrap(self) -> Awaitable[T]:
        """
        Return the Ok value or raise the Err as an exception.

        This is a terminal operation that unwraps the Result.

        Returns:
            Awaitable[T] that will return the value or raise the error

        Example:
            message = await Mediator.send_async(query).map(...).unwrap()
        """

        async def unwrapped() -> T:
            _result: Result[T, E] = await self
            if is_ok(_result):
                return _result.unwrap()
            # Since Err.unwrap() is removed, raise the error explicitly
            # TypeIs ensures that if not is_ok, then it must be Err
            raise _result.error

        return unwrapped()

    def map_err[F: Exception](self, f: Callable[[E], F]) -> "ResultAwaitable[T, F]":
        """
        Transform the error value using the provided function asynchronously.

        Args:
            f: Function to apply to the error value (E -> F)

        Returns:
            ResultAwaitable[T, F] wrapping the result with transformed error type

        Example:
            await (
                Mediator.send_async(cmd)
                .map_err(lambda e: DatabaseError(f"DB error: {e}"))
                .unwrap()
            )
        """

        async def mapped() -> Result[T, F]:
            _result: Result[T, E] = await self
            return _result.map_err(f)

        return ResultAwaitable(mapped())
