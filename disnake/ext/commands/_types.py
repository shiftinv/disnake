# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, Protocol, TypeVar, Union

if TYPE_CHECKING:
    from disnake import ApplicationCommandInteraction

    from .cog import Cog
    from .context import Context
    from .core import Command
    from .errors import CommandError

T = TypeVar("T")

FuncT = TypeVar("FuncT", bound=Callable[..., Any])

CogT = TypeVar("CogT", bound="Optional[Cog]")
ContextT = TypeVar("ContextT", bound="Context[Any]")
CommandInteractionT = TypeVar("CommandInteractionT", bound="ApplicationCommandInteraction[Any]")

Coro = Coroutine[Any, Any, T]
MaybeCoro = Union[T, Coro[T]]
CoroFunc = Callable[..., Coro[Any]]

CheckInput = Callable[["Context[Any]"], MaybeCoro[bool]]
# similar to `CheckInput`, but always returns a coroutine
CheckPredicate = Callable[[Context[Any]], Coro[bool]]
CommandT = TypeVar("CommandT", bound="Union[Command[Any, ..., Any], CoroFunc]")


class CheckDecorator(Protocol):
    predicate: CheckPredicate

    def __call__(self, func: CommandT) -> CommandT: ...


AppCheck = Union[
    Callable[["Cog", "ApplicationCommandInteraction"], MaybeCoro[bool]],
    Callable[["ApplicationCommandInteraction"], MaybeCoro[bool]],
]

Hook = Union[
    Callable[[CogT, ContextT], Coro[Any]],
    Callable[[ContextT], Coro[Any]],
]
AppHook = Union[
    Callable[[CogT, CommandInteractionT], Coro[Any]],
    Callable[[CommandInteractionT], Coro[Any]],
]

CommandErrorT = TypeVar("CommandErrorT", bound="CommandError")
Error = Union[
    Callable[[CogT, ContextT, CommandErrorT], Coro[Any]],
    Callable[[ContextT, CommandErrorT], Coro[Any]],
]
AppError = Union[
    Callable[[CogT, CommandInteractionT, CommandErrorT], Coro[Any]],
    Callable[[CommandInteractionT, CommandErrorT], Coro[Any]],
]


# This is merely a tag type to avoid circular import issues.
# Yes, this is a terrible solution but ultimately it is the only solution.
class _BaseCommand:
    __slots__ = ()
