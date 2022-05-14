# SPDX-License-Identifier: MIT

# pyright: reportIncompatibleMethodOverride=true
# pyright: reportIncompatibleVariableOverride=true

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Callable,
    Dict,
    Generic,
    Iterable,
    Iterator,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from .app_commands import application_command_factory
from .audit_logs import AuditLogEntry
from .automod import AutoModRule
from .bans import BanEntry
from .guild_scheduled_event import GuildScheduledEvent
from .integrations import PartialIntegration
from .threads import Thread
from .utils import MISSING, parse_time, snowflake_time, time_snowflake

if TYPE_CHECKING:
    from .abc import Messageable, MessageableChannel, Snowflake, SnowflakeTime  # TODO: allow int
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
    from .types.threads import Thread as ThreadPayload
    from .types.user import User as UserPayload
    from .user import User
    from .webhook import Webhook

# TODO: update examples in docstrings
# TODO: oldest_first for baniterator + historyiterator

__all__ = (
    "BaseIterator",
    "ChunkIterator",
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


class BaseIterator(AsyncIterator[T], ABC):
    def __aiter__(self) -> AsyncIterator[T]:
        return self

    @abstractmethod
    async def __anext__(self) -> T:
        raise NotImplementedError


class ChunkIterator(BaseIterator[T], Generic[RawT, T], ABC):
    def __init__(self, *, limit: Optional[int], chunk_size: int):
        self._limit: int = limit if limit is not None else sys.maxsize
        if self._limit <= 0:
            raise ValueError("Limit must be > 0")
        self._chunk_size: int = chunk_size

        self._filter: Optional[Callable[[RawT], bool]] = None
        self.__it: Iterator[RawT] = iter(())

    async def __anext__(self) -> T:
        try:
            value = next(self.__it)
        except StopIteration:
            # if chunk is finished and we don't expect more, exit
            if self._next_limit <= 0:
                raise StopAsyncIteration

            # get new chunk, filter if needed
            result_len, result = await self._get_chunk()
            self.__it = iter(result)

            # update remaining limit
            self._limit -= result_len

            # if we received fewer items than max chunk size,
            # we either reached the last chunk or the limit was lower than the chunk size,
            # in which case we won't send any further requests
            if result_len < self._chunk_size:
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
        return min(self._chunk_size, self._limit)

    @abstractmethod
    async def _get_chunk(self) -> Tuple[int, Iterable[RawT]]:
        raise NotImplementedError

    @abstractmethod
    def _transform(self, data: RawT) -> T:
        raise NotImplementedError


class ReactionIterator(ChunkIterator["UserPayload", Union["User", "Member"]]):
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
            self._filter = lambda e: int(e["id"]) < _before

    async def _get_chunk(self) -> Tuple[int, Iterable[UserPayload]]:
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

        return len(data), data

    def _transform(self, data: UserPayload) -> Union[User, Member]:
        if self._guild is not None:
            member_id = int(data["id"])
            if member := self._guild.get_member(member_id):
                return member
        return self._state.create_user(data)


class HistoryIterator(ChunkIterator["MessagePayload", "Message"]):
    def __init__(
        self,
        *,
        messageable: Messageable,
        before: Optional[SnowflakeTime] = None,
        after: Optional[SnowflakeTime] = None,
        around: Optional[SnowflakeTime] = None,
        limit: Optional[int] = None,
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

        if _around is not None:
            self._around = _around
            if _before is not None:
                if _after is not None:
                    self._filter = lambda m: _after < int(m["id"]) < _before
                else:
                    self._filter = lambda m: int(m["id"]) < _before
            elif _after is not None:
                self._filter = lambda m: _after < int(m["id"])

        elif _after is not None:
            self._after = _after
            if _before is not None:
                self._filter = lambda m: int(m["id"]) < _before

        elif _before is not None:
            self._before = _before

    async def _get_chunk(self) -> Tuple[int, Iterable[MessagePayload]]:
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
            result = data
        elif self._after is not None:
            self._after = int(data[0]["id"])
            result = reversed(data)
        else:
            self._before = int(data[-1]["id"])
            result = data

        return len(data), result

    def _transform(self, data: MessagePayload) -> Message:
        return self._messageable._state.create_message(channel=self._channel, data=data)


class BanIterator(ChunkIterator["BanPayload", "BanEntry"]):
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
            if _after is not None:
                self._filter = lambda b: _after < int(b["user"]["id"])
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Tuple[int, Iterable[BanPayload]]:
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
            result = reversed(data)
        else:
            self._after = int(data[-1]["user"]["id"])
            result = data

        return len(data), result

    def _transform(self, data: BanPayload) -> BanEntry:
        return BanEntry(
            user=self._guild._state.create_user(data=data["user"]),
            reason=data["reason"],
        )


class AuditLogIterator(ChunkIterator["AuditLogEntryPayload", "AuditLogEntry"]):
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
            self._filter = lambda e: _after < int(e["id"])

        self._application_commands: Dict[int, APIApplicationCommand] = {}
        self._automod_rules: Dict[int, AutoModRule] = {}
        self._guild_scheduled_events: Dict[int, GuildScheduledEvent] = {}
        self._integrations: Dict[int, PartialIntegration] = {}
        self._threads: Dict[int, Thread] = {}
        self._users: Dict[int, User] = {}
        self._webhooks: Dict[int, Webhook] = {}

    async def _get_chunk(self) -> Tuple[int, Iterable[AuditLogEntryPayload]]:
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

        return len(entries), entries

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


class GuildIterator(ChunkIterator["GuildPayload", "Guild"]):
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
            if _after is not None:
                self._filter = lambda g: _after < int(g["id"])
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Tuple[int, Iterable[GuildPayload]]:
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
            result = reversed(data)
        else:
            self._after = int(data[-1]["id"])
            result = data

        return len(data), result

    def _transform(self, data: GuildPayload) -> Guild:
        from .guild import Guild  # cyclic import

        return Guild(state=self._state, data=data)


class MemberIterator(ChunkIterator["MemberWithUserPayload", "Member"]):
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
            self._filter = lambda e: int(e["user"]["id"]) < _before

    async def _get_chunk(self) -> Tuple[int, Iterable[MemberWithUserPayload]]:
        data = await self._request(
            guild_id=self._guild.id,
            limit=self._next_limit,
            after=self._after,
        )

        if not data:
            raise StopAsyncIteration

        self._after = int(data[-1]["user"]["id"])

        return len(data), data

    def _transform(self, data: MemberWithUserPayload) -> Member:
        from .member import Member  # cyclic import

        return Member(guild=self._guild, state=self._state, data=data)


class ArchivedThreadIterator(ChunkIterator["ThreadPayload", "Thread"]):
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
        super().__init__(limit=limit, chunk_size=100)

        self._channel_id: int = channel_id
        self._guild: Guild = guild

        if joined and not private:
            raise ValueError("Cannot iterate over joined public archived threads")

        self._get_key: Callable[[ThreadPayload], str]
        http = guild._state.http
        if joined:
            self._request = http.get_joined_private_archived_threads
            self._get_key = lambda t: str(t["id"])
        else:
            if private:
                self._request = http.get_private_archived_threads
            else:
                self._request = http.get_public_archived_threads
            self._get_key = lambda t: t["thread_metadata"]["archive_timestamp"]

        self._before: Optional[str]  # snowflake string or iso timestamp
        _after: Optional[int]  # snowflake int
        _before, _after = _convert_before_after(before, after)

        if _before is None:
            self._before = None
        else:
            if joined:
                self._before = str(_before)
            else:
                self._before = snowflake_time(_before).isoformat()

        # TODO: swap these ifs around?
        if _after is not None:
            if joined:
                self._filter = lambda t: _after < int(self._get_key(t))
            else:
                self._filter = lambda t: _after < time_snowflake(
                    parse_time(self._get_key(t)), high=True
                )

    async def _get_chunk(self) -> Tuple[int, Iterable[ThreadPayload]]:
        data = await self._request(
            channel_id=self._channel_id,
            # API requires a minimum of 2, thanks Discord
            limit=max(self._next_limit, 2),
            before=self._before,
        )

        threads = data["threads"]
        if not threads:
            raise StopAsyncIteration

        self._before = self._get_key(threads[-1])

        if not data.get("has_more", False):
            # this is the last page
            self._limit = 0

        return len(threads), threads

    def _transform(self, data: ThreadPayload) -> Thread:
        from .threads import Thread

        return Thread(guild=self._guild, state=self._guild._state, data=data)


class GuildScheduledEventUserIterator(
    ChunkIterator["GuildScheduledEventUserPayload", Union["User", "Member"]]
):
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
            if _after is not None:
                self._filter = lambda b: _after < int(b["user"]["id"])
        elif _after is not None:
            self._after = _after

    async def _get_chunk(self) -> Tuple[int, Iterable[GuildScheduledEventUserPayload]]:
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
            result = reversed(data)
        else:
            self._after = int(data[-1]["user"]["id"])
            result = data

        return len(data), result

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
