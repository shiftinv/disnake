# SPDX-License-Identifier: MIT

# pyright: reportIncompatibleMethodOverride=true
# pyright: reportIncompatibleVariableOverride=true

from __future__ import annotations

import asyncio
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Dict,
    Generic,
    Iterator,
    List,
    NoReturn,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    overload,
)

from .app_commands import application_command_factory
from .audit_logs import AuditLogEntry
from .automod import AutoModRule
from .bans import BanEntry
from .guild_scheduled_event import GuildScheduledEvent
from .integrations import PartialIntegration
from .threads import Thread
from .utils import MISSING, maybe_coroutine, parse_time, snowflake_time, time_snowflake

if TYPE_CHECKING:
    from typing_extensions import TypeGuard

    from .abc import Messageable, MessageableChannel, Snowflake, SnowflakeTime
    from .app_commands import APIApplicationCommand
    from .client import Client
    from .guild import Guild
    from .member import Member
    from .message import Message
    from .types.audit_log import AuditLogEntry as AuditLogEntryPayload, AuditLogEvent
    from .types.guild import Ban as BanPayload, Guild as GuildPayload
    from .types.guild_scheduled_event import (
        GuildScheduledEventUser as GuildScheduledEventUserPayload,
    )
    from .types.member import MemberWithUser as MemberWithUserPayload
    from .types.message import Message as MessagePayload
    from .types.threads import Thread as ThreadPayload, ThreadMember as ThreadMemberPayload
    from .types.user import User as UserPayload
    from .user import User
    from .webhook import Webhook

__all__ = (
    "BaseIterator",
    "PageIterator",
    "ReactionIterator",
    "HistoryIterator",
    "BanIterator",
    "AuditLogIterator",
    "GuildIterator",
    "MemberIterator",
    "ArchivedThreadIterator",
    "GuildScheduledEventUserIterator",
)


T = TypeVar("T")
RawT = TypeVar("RawT")
OT = TypeVar("OT")

_Func = Callable[[T], Union[OT, Coroutine[Any, Any, OT]]]


# this could use overloads, but they're not needed
def _convert_snowflake_datetime(s: Optional[SnowflakeTime], *, high: bool) -> Optional[int]:
    if s is None:
        return None
    elif isinstance(s, datetime):
        return time_snowflake(s, high=high)
    return s.id


def _convert_before_after(
    before: Optional[SnowflakeTime], after: Optional[SnowflakeTime]
) -> Tuple[Optional[int], Optional[int]]:
    _before = _convert_snowflake_datetime(before, high=False)
    _after = _convert_snowflake_datetime(after, high=True)
    return _before, _after


if TYPE_CHECKING:

    def _is_coro_func(func: _Func[T, OT]) -> TypeGuard[Callable[[T], Coroutine[Any, Any, OT]]]:
        ...

else:
    _is_coro_func = asyncio.iscoroutinefunction


class BaseIterator(AsyncIterator[T], ABC):
    __slots__ = ()

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    @abstractmethod
    async def __anext__(self) -> T:
        raise NotImplementedError

    def map(self, func: _Func[T, OT]) -> BaseIterator[OT]:
        return _MapIterator(self, func)

    def filter(self, func: _Func[T, bool]) -> BaseIterator[T]:
        return _FilterIterator(self, func)

    def enumerate(self, start: int = 0) -> BaseIterator[Tuple[int, T]]:
        return _EnumerateIterator(self, start)

    @overload
    async def find(self, func: _Func[T, bool]) -> Optional[T]:
        ...

    @overload
    async def find(self, func: _Func[T, bool], default: OT) -> Union[T, OT]:
        ...

    async def find(self, func: _Func[T, bool], default: OT = None) -> Optional[Union[T, OT]]:
        if _is_coro_func(func):
            async for value in self:
                if await func(value):
                    return value
        else:
            async for value in self:
                if func(value):
                    return value

        return default

    async def foreach(self, func: _Func[T, Any]) -> None:
        if _is_coro_func(func):
            async for value in self:
                await func(value)
        else:
            async for value in self:
                func(value)

    async def count(self) -> int:
        num = 0
        async for _ in self:
            num += 1
        return num

    def chunk(self, max_size: int) -> BaseIterator[Sequence[T]]:
        if max_size <= 0:
            raise ValueError("Chunk size must be > 0")
        return _ChunkIterator(self, max_size)

    def take_while(self, func: _Func[T, bool]) -> BaseIterator[T]:
        return _TakeWhileIterator(self, func)

    def drop_while(self, func: _Func[T, bool]) -> BaseIterator[T]:
        return _DropWhileIterator(self, func)

    if not TYPE_CHECKING:

        def __iter__(self) -> NoReturn:
            raise TypeError("This is an async iterator - use `async for` instead of `for`.")

        def __next__(self) -> NoReturn:
            instead = (
                "await anext(it)" if sys.version_info[:2] >= (3, 10) else "await it.__anext__()"
            )
            raise TypeError(f"This is an async iterator - use `{instead}` instead of `next(it)`.")


class _MapIterator(BaseIterator[OT]):
    __slots__ = ("_it", "_func")

    def __init__(self, it: BaseIterator[T], func: _Func[T, OT]):
        self._it = it
        self._func = func

    async def __anext__(self) -> OT:
        value = await self._it.__anext__()
        return await maybe_coroutine(self._func, value)


class _FilterIterator(BaseIterator[T]):
    __slots__ = ("_it", "_func")

    def __init__(self, it: BaseIterator[T], func: _Func[T, bool]):
        self._it = it
        self._func = func

    async def __anext__(self) -> T:
        async for value in self._it:
            if await maybe_coroutine(self._func, value):
                return value
        raise StopAsyncIteration


class _EnumerateIterator(BaseIterator[Tuple[int, T]]):
    __slots__ = ("_it", "_index")

    def __init__(self, it: BaseIterator[T], start: int):
        self._it = it
        self._index = start

    async def __anext__(self) -> Tuple[int, T]:
        v = await self._it.__anext__()
        i = self._index
        self._index += 1
        return i, v


class _TakeWhileIterator(BaseIterator[T]):
    __slots__ = ("_it", "_func")

    def __init__(self, it: BaseIterator[T], func: _Func[T, bool]):
        self._it = it
        self._func = func

    async def __anext__(self) -> T:
        value = await self._it.__anext__()
        if await maybe_coroutine(self._func, value):
            return value
        raise StopAsyncIteration


class _DropWhileIterator(BaseIterator[T]):
    __slots__ = ("_it", "_func", "_pass")

    def __init__(self, it: BaseIterator[T], func: _Func[T, bool]):
        self._it = it
        self._func = func
        # whether check func failed before, in which case we return all subsequent items
        self._pass = False

    async def __anext__(self) -> T:
        if self._pass:
            return await self._it.__anext__()

        # find first item that doesn't match
        while True:
            value = await self._it.__anext__()
            if not await maybe_coroutine(self._func, value):
                break
        self._pass = True
        return value


class _ChunkIterator(BaseIterator[Sequence[T]]):
    __slots__ = ("_it", "_max_size")

    def __init__(self, it: BaseIterator[T], max_size: int):
        self._it = it
        self._max_size = max_size

    async def __anext__(self) -> Sequence[T]:
        chunk: List[T] = []

        async for value in self._it:
            chunk.append(value)
            if len(chunk) == self._max_size:
                break

        if chunk:
            return chunk
        raise StopAsyncIteration


class PageIterator(BaseIterator[T], Generic[RawT, T], ABC):
    __slots__ = (
        "_limit",
        "_max_chunk_size",
        "_min_expected_chunk_size",
        "_filter",
        "_reverse",
        "__it",
    )

    def __init__(
        self,
        *,
        limit: Optional[int],
        chunk_size: int,
        min_expected_chunk_size: int = MISSING,
    ):
        self._limit: int = limit if limit is not None else sys.maxsize
        if self._limit <= 0:
            raise ValueError("Limit must be > 0")

        # these are generally the same, but the expected size can be changed if an
        # endpoint uses a slightly different pagination mechanism (e.g. `has_more`)
        self._max_chunk_size: int = chunk_size
        self._min_expected_chunk_size: int = (
            self._max_chunk_size if min_expected_chunk_size is MISSING else min_expected_chunk_size
        )

        self._filter: Optional[Callable[[RawT], bool]] = None
        self._reverse: bool = False
        self.__it: Iterator[RawT] = iter(())

    async def __anext__(self) -> T:
        try:
            value = next(self.__it)
        except StopIteration:
            # if chunk is finished and we don't expect more, exit
            if self._next_limit <= 0:
                raise StopAsyncIteration

            # get new chunk, reverse if needed
            result = await self._get_chunk()
            result_len = len(result)
            if self._reverse:
                result = reversed(result)
            self.__it = iter(result)

            # update remaining limit
            self._limit -= result_len

            # if we received fewer items than expected,
            # we either reached the last chunk or the requested limit was lower than the chunk size,
            # in which case we won't send any further requests
            if result_len < self._min_expected_chunk_size:
                self._limit = 0

            # get value from new chunk
            try:
                value = next(self.__it)
            except StopIteration:
                # if new chunk was empty, we're done
                raise StopAsyncIteration

        if self._filter is not None and not self._filter(value):
            raise StopAsyncIteration
        return self._transform(value)

    @property
    def _next_limit(self) -> int:
        return min(self._max_chunk_size, self._limit)

    def _set_filter(self, filter: Optional[Callable[[RawT], bool]]) -> None:
        self._filter = filter

    def _set_reverse(self, reverse: bool) -> None:
        self._reverse = reverse

    @abstractmethod
    async def _get_chunk(self) -> Sequence[RawT]:
        raise NotImplementedError

    @abstractmethod
    def _transform(self, data: RawT) -> T:
        raise NotImplementedError


class ReactionIterator(PageIterator["UserPayload", Union["User", "Member"]]):
    __slots__ = (
        "_request",
        "_state",
        "_message_id",
        "_channel_id",
        "_emoji",
        "_guild",
        "_after",
    )

    def __init__(
        self,
        *,
        message: Message,
        emoji: str,
        before: Optional[Snowflake] = None,
        after: Optional[Snowflake] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=100)

        self._message_id: int = message.id
        self._channel_id: int = message.channel.id
        self._emoji: str = emoji

        from .guild import Guild  # cyclic import

        # filter `Object` just in case
        self._guild: Optional[Guild] = message.guild if isinstance(message.guild, Guild) else None

        self._request = message._state.http.get_reaction_users
        self._state = message._state

        _before: Optional[int]
        self._after: Optional[int]
        _before, self._after = _convert_before_after(before, after)

        if _before is not None:
            self._set_filter(lambda e: int(e["id"]) < _before)

    async def _get_chunk(self) -> Sequence[UserPayload]:
        data = await self._request(
            channel_id=self._channel_id,
            message_id=self._message_id,
            emoji=self._emoji,
            limit=self._next_limit,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        self._after = int(data[-1]["id"])

        return data

    def _transform(self, data: UserPayload) -> Union[User, Member]:
        if self._guild is not None:
            member_id = int(data["id"])
            if member := self._guild.get_member(member_id):
                return member
        return self._state.create_user(data)


class HistoryIterator(PageIterator["MessagePayload", "Message"]):
    __slots__ = ("_request", "_messageable", "_channel", "_before", "_after", "_around")

    def __init__(
        self,
        *,
        messageable: Messageable,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        around: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
        oldest_first: bool = None,
    ):
        if around is not None and limit is not None:
            # API only allows <= 100, but always returns the next larger odd number of messages
            # when `around` is used, which means up to 101
            if limit > 101:
                raise ValueError("History max limit is 101 when specifying `around` parameter")
            elif limit == 101:
                limit = 100

        super().__init__(limit=limit, chunk_size=100)

        self._messageable: Messageable = messageable
        # set later as we need an async func
        self._channel: MessageableChannel = MISSING

        self._request = messageable._state.http.logs_from

        self._before: Optional[int] = None
        self._after: Optional[int] = None
        self._around: Optional[int] = None
        _before, _after = _convert_before_after(before, after)
        _around = _convert_snowflake_datetime(around, high=False)

        if oldest_first is None:
            reverse = _after is not None
        else:
            reverse = oldest_first
        self._set_reverse(reverse)

        if _around is not None:
            self._around = _around
            if _before is not None:
                if _after is not None:
                    self._set_filter(lambda m: _after < int(m["id"]) < _before)
                else:
                    self._set_filter(lambda m: int(m["id"]) < _before)
            elif _after is not None:
                self._set_filter(lambda m: _after < int(m["id"]))

        elif reverse:
            self._after = _after or 0  # make sure `_after` is not `None` to use it for pagination
            if _before is not None:
                self._set_filter(lambda m: int(m["id"]) < _before)

        else:
            self._before = _before
            if _after is not None:
                self._set_filter(lambda m: _after < int(m["id"]))

    async def _get_chunk(self) -> Sequence[MessagePayload]:
        if self._channel is MISSING:
            self._channel = await self._messageable._get_channel()

        data = await self._request(
            channel_id=self._channel.id,
            limit=self._next_limit,
            # only one of these is set
            before=self._before,
            after=self._after,
            around=self._around,
        )

        if not data:
            raise StopAsyncIteration

        # API always returns items in descending order
        if self._around is not None:
            self._limit = 0  # we don't do any pagination with `around`
        elif self._after is not None:
            self._after = int(data[0]["id"])
        else:
            self._before = int(data[-1]["id"])

        return data

    def _transform(self, data: MessagePayload) -> Message:
        return self._messageable._state.create_message(channel=self._channel, data=data)


class BanIterator(PageIterator["BanPayload", "BanEntry"]):
    __slots__ = ("_request", "_guild", "_before", "_after")

    def __init__(
        self,
        *,
        guild: Guild,
        before: Optional[Snowflake] = None,
        after: Optional[Snowflake] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=1000)

        self._guild: Guild = guild

        self._request = guild._state.http.get_bans

        self._before: Optional[int] = None
        self._after: Optional[int] = None
        _before, _after = _convert_before_after(before, after)

        if _before is not None:
            self._before = _before
            self._set_reverse(True)
            if _after is not None:
                self._set_filter(lambda b: _after < int(b["user"]["id"]))
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Sequence[BanPayload]:
        data = await self._request(
            guild_id=self._guild.id,
            limit=self._next_limit,
            # only one of these is set
            before=self._before,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        # API always returns items in ascending order
        if self._before is not None:
            self._before = int(data[0]["user"]["id"])
        else:
            self._after = int(data[-1]["user"]["id"])

        return data

    def _transform(self, data: BanPayload) -> BanEntry:
        return BanEntry(
            user=self._guild._state.create_user(data=data["user"]),
            reason=data["reason"],
        )


class AuditLogIterator(PageIterator["AuditLogEntryPayload", "AuditLogEntry"]):
    __slots__ = (
        "_request",
        "_guild",
        "_user_id",
        "_action_type",
        "_before",
        "_application_commands",
        "_guild_scheduled_events",
        "_integrations",
        "_threads",
        "_users",
        "_webhooks",
    )

    def __init__(
        self,
        *,
        guild: Guild,
        user_id: Optional[int] = None,
        action_type: Optional[AuditLogEvent] = None,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=100)

        self._guild: Guild = guild
        self._user_id: Optional[int] = user_id
        self._action_type: Optional[AuditLogEvent] = action_type

        self._request = guild._state.http.get_audit_logs

        self._before: Optional[int]
        _after: Optional[int]
        self._before, _after = _convert_before_after(before, after)

        if _after is not None:
            self._set_filter(lambda e: _after < int(e["id"]))

        self._application_commands: Dict[int, APIApplicationCommand] = {}
        self._automod_rules: Dict[int, AutoModRule] = {}
        self._guild_scheduled_events: Dict[int, GuildScheduledEvent] = {}
        self._integrations: Dict[int, PartialIntegration] = {}
        self._threads: Dict[int, Thread] = {}
        self._users: Dict[int, User] = {}
        self._webhooks: Dict[int, Webhook] = {}

    async def _get_chunk(self) -> Sequence[AuditLogEntryPayload]:
        data = await self._request(
            guild_id=self._guild.id,
            limit=self._next_limit,
            before=self._before,
            user_id=self._user_id,
            action_type=self._action_type,
        )

        entries = data.get("audit_log_entries", [])
        if not entries:
            raise StopAsyncIteration

        self._before = int(entries[-1]["id"])

        state = self._guild._state

        self._application_commands = {
            int(d["id"]): application_command_factory(d)
            for d in data.get("application_commands", [])
        }

        self._automod_rules = {
            int(d["id"]): AutoModRule(guild=self._guild, data=d)
            for d in data.get("auto_moderation_rules", [])
        }

        self._guild_scheduled_events = {
            int(d["id"]): GuildScheduledEvent(state=state, data=d)
            for d in data.get("guild_scheduled_events", [])
        }

        self._integrations = {
            int(d["id"]): PartialIntegration(guild=self._guild, data=d)
            for d in data.get("integrations", [])
        }

        self._threads = {
            int(d["id"]): Thread(guild=self._guild, state=state, data=d)
            for d in data.get("threads", [])
        }

        self._users = {int(d["id"]): state.create_user(d) for d in data.get("users", [])}

        self._webhooks = {int(d["id"]): state.create_webhook(d) for d in data.get("webhooks", [])}

        return entries

    def _transform(self, data: AuditLogEntryPayload) -> AuditLogEntry:
        return AuditLogEntry(
            data=data,
            guild=self._guild,
            application_commands=self._application_commands,
            automod_rules=self._automod_rules,
            guild_scheduled_events=self._guild_scheduled_events,
            integrations=self._integrations,
            threads=self._threads,
            users=self._users,
            webhooks=self._webhooks,
        )


class GuildIterator(PageIterator["GuildPayload", "Guild"]):
    __slots__ = ("_request", "_state", "_before", "_after")

    def __init__(
        self,
        *,
        client: Client,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=200)

        self._request = client.http.get_guilds
        self._state = client._connection

        self._before: Optional[int] = None
        self._after: Optional[int] = None
        _before, _after = _convert_before_after(before, after)

        if _before is not None:
            self._before = _before
            self._set_reverse(True)
            if _after is not None:
                self._set_filter(lambda g: _after < int(g["id"]))
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Sequence[GuildPayload]:
        data = await self._request(
            limit=self._next_limit,
            # only one of these is set
            before=self._before,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        # API always returns items in ascending order
        if self._before is not None:
            self._before = int(data[0]["id"])
        else:
            self._after = int(data[-1]["id"])

        return data

    def _transform(self, data: GuildPayload) -> Guild:
        from .guild import Guild  # cyclic import

        return Guild(state=self._state, data=data)


class MemberIterator(PageIterator["MemberWithUserPayload", "Member"]):
    __slots__ = ("_request", "_state", "_guild", "_after")

    def __init__(
        self,
        *,
        guild: Guild,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=1000)

        self._guild: Guild = guild

        self._request = guild._state.http.get_members
        self._state = guild._state

        _before: Optional[int]
        self._after: Optional[int]
        _before, self._after = _convert_before_after(before, after)

        if _before is not None:
            self._set_filter(lambda e: int(e["user"]["id"]) < _before)

    async def _get_chunk(self) -> Sequence[MemberWithUserPayload]:
        data = await self._request(
            guild_id=self._guild.id,
            limit=self._next_limit,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        self._after = int(data[-1]["user"]["id"])

        return data

    def _transform(self, data: MemberWithUserPayload) -> Member:
        from .member import Member  # cyclic import

        return Member(guild=self._guild, state=self._state, data=data)


class ArchivedThreadIterator(PageIterator["ThreadPayload", "Thread"]):
    __slots__ = ("_request", "_guild", "_channel_id", "_get_key", "_before")

    def __init__(
        self,
        *,
        channel_id: int,
        guild: Guild,
        joined: bool,
        private: bool,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(
            limit=limit,
            chunk_size=100,
            # pagination mainly works using `has_more`, but since we can theoretically
            # receive a chunk smaller than the max size but with `has_more=True`,
            # we don't want to stop at that point, so we only expect at least 1 item per chunk
            # to continue fetching pages instead of 100
            min_expected_chunk_size=1,
        )

        self._channel_id: int = channel_id
        self._guild: Guild = guild

        if joined and not private:
            raise ValueError("Cannot iterate over joined public archived threads")

        self._before: Optional[str] = None  # snowflake string or iso timestamp
        _after: Optional[int]  # snowflake int
        _before, _after = _convert_before_after(before, after)

        self._get_key: Callable[[ThreadPayload], str]
        http = guild._state.http
        if joined:
            self._request = http.get_joined_private_archived_threads
            self._get_key = lambda t: str(t["id"])

            if _before is not None:
                self._before = str(_before)
            if _after is not None:
                self._set_filter(lambda t: _after < int(self._get_key(t)))
        else:
            if private:
                self._request = http.get_private_archived_threads
            else:
                self._request = http.get_public_archived_threads
            self._get_key = lambda t: t["thread_metadata"]["archive_timestamp"]

            if _before is not None:
                self._before = snowflake_time(_before).isoformat()
            if _after is not None:
                _after_ts = snowflake_time(_after)  # small optimization
                self._set_filter(lambda t: _after_ts < parse_time(self._get_key(t)))

    async def _get_chunk(self) -> Sequence[ThreadPayload]:
        limit = self._next_limit
        data = await self._request(
            channel_id=self._channel_id,
            # API requires a minimum of 2, thanks Discord
            limit=max(limit, 2),
            before=self._before,
        )

        threads = data["threads"]
        if len(threads) > limit:
            # manually limit if we received more than needed, see above
            threads = threads[:limit]
        if not threads:
            raise StopAsyncIteration

        # insert thread member objects into threads
        self._add_members(threads, data["members"])

        # update pagination params
        self._before = self._get_key(threads[-1])

        if not data.get("has_more", False):
            # this is the last page
            self._limit = 0

        return threads

    def _transform(self, data: ThreadPayload) -> Thread:
        from .threads import Thread

        return Thread(guild=self._guild, state=self._guild._state, data=data)

    def _add_members(
        self, threads: List[ThreadPayload], members: List[ThreadMemberPayload]
    ) -> None:
        self_id = self._guild._state.user.id
        member_dict: Dict[int, ThreadMemberPayload] = {}
        for m in members:
            if not (thread_id := m.get("id")) or not (user_id := m.get("user_id")):
                continue
            # we only expect thread member objects of the client user, but check to make sure
            if int(user_id) != self_id:
                continue
            member_dict[int(thread_id)] = m

        for thread in threads:
            if member := member_dict.get(int(thread["id"])):
                thread["member"] = member


class GuildScheduledEventUserIterator(
    PageIterator["GuildScheduledEventUserPayload", Union["User", "Member"]]
):
    __slots__ = ("_request", "_event", "_with_members", "_before", "_after")

    def __init__(
        self,
        *,
        event: GuildScheduledEvent,
        with_members: bool,
        before: Optional[Snowflake] = None,
        after: Optional[Snowflake] = None,
        limit: Optional[int] = None,
    ):
        super().__init__(limit=limit, chunk_size=100)

        self._event: GuildScheduledEvent = event
        self._with_members: bool = with_members

        self._request = event._state.http.get_guild_scheduled_event_users

        self._before: Optional[int] = None
        self._after: Optional[int] = None
        _before, _after = _convert_before_after(before, after)

        if _before is not None:
            self._before = _before
            self._set_reverse(True)
            if _after is not None:
                self._set_filter(lambda b: _after < int(b["user"]["id"]))
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Sequence[GuildScheduledEventUserPayload]:
        data = await self._request(
            guild_id=self._event.guild_id,
            event_id=self._event.id,
            with_member=self._with_members,
            limit=self._next_limit,
            # only one of these is set
            before=self._before,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        # API always returns items in ascending order
        if self._before is not None:
            self._before = int(data[0]["user"]["id"])
        else:
            self._after = int(data[-1]["user"]["id"])

        return data

    def _transform(self, data: GuildScheduledEventUserPayload) -> Union[User, Member]:
        from .member import Member  # cyclic import

        user_data = data["user"]
        member_data = data.get("member")
        if member_data is not None and (guild := self._event.guild) is not None:
            return guild.get_member(int(user_data["id"])) or Member(
                data=member_data, user_data=user_data, guild=guild, state=self._event._state
            )
        else:
            return self._event._state.store_user(data["user"])
