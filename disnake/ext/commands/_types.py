# SPDX-License-Identifier: MIT

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, TypeVar, Union

if TYPE_CHECKING:
    from disnake import ApplicationCommandInteraction

    from .cog import Cog
    from .context import Context
    from .errors import CommandError

T = TypeVar("T")

FuncT = TypeVar("FuncT", bound=Callable[..., Any])

CogT = TypeVar("CogT", bound="Optional[Cog]")
ContextT = TypeVar("ContextT", bound="Context[Any]")
CommandInteractionT = TypeVar("CommandInteractionT", bound="ApplicationCommandInteraction[Any]")

Coro = Coroutine[Any, Any, T]
MaybeCoro = Union[T, Coro[T]]
CoroFunc = Callable[..., Coro[Any]]

Check = Union[
    Callable[["Cog", "Context[Any]"], MaybeCoro[bool]], Callable[["Context[Any]"], MaybeCoro[bool]]
]
AppCheck = Union[
    Callable[["Cog", "ApplicationCommandInteraction"], MaybeCoro[bool]],
    Callable[["ApplicationCommandInteraction"], MaybeCoro[bool]],
]
Hook = Union[Callable[["Cog", "Context[Any]"], Coro[Any]], Callable[["Context[Any]"], Coro[Any]]]

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
