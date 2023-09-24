# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, SupportsInt, Type, Union

from . import utils
from .mixins import Hashable

if TYPE_CHECKING:
    import datetime

    from .abc import Snowflake

    SupportsIntCast = Union[SupportsInt, str, bytes, bytearray]

__all__ = ("Object",)


class Object(Hashable):
    """Represents a generic Discord object.

    The purpose of this class is to allow you to create 'miniature'
    versions of data classes if you want to pass in just an ID. Some functions
    that take in a specific data class with an ID can also take in this class
    as a substitute instead. Note that even though this is the case, not all
    objects (if any) actually inherit from this class.

    There are also some cases where some websocket events are received
    in :issue-dpy:`strange order <21>` and when such events happened you would
    receive this class rather than the actual data class. These cases are
    extremely rare.

    .. container:: operations

        .. describe:: x == y

            Checks if two objects are equal.

        .. describe:: x != y

            Checks if two objects are not equal.

        .. describe:: hash(x)

            Returns the object's hash.

    Attributes
    ----------
    id: :class:`int`
        The ID of the object.
    """

    # TODO: default `type` to MISSING?
    def __init__(self, id: SupportsIntCast, *, type: Optional[Type[Snowflake]] = None) -> None:
        try:
            id = int(id)
        except ValueError:
            raise TypeError(
                f"id parameter must be convertable to int not {id.__class__!r}"
            ) from None

        self.id: int = id
        # TODO: default to `type(self)`?
        self.type: Optional[Type[Snowflake]] = type

    def __eq__(self, other: object) -> bool:
        # Note: this intentionally does not use `isinstance` for `self.type`,
        # mirroring the effective behavior of `EqualityComparable.__eq__`
        # (when one operand is a subtype of the other, the interpreter uses the subtype's __eq__,
        # turning the `isinstance` in `EqualityComparable.__eq__` into what is
        # essentially just `type(a) == type(b)`)
        return (
            isinstance(other, self.__class__)
            and self.id == other.id
            # If one Object has a `type` and the other one doesn't, still consider them equivalent.
            # This makes the relation non-transitive (since `<Object type=A> == <Object> == <Object type=B>`,
            # but `<Object type=A> != <Object type=B>`), but ensures compatibility with existing code.
            and (self.type == other.type or self.type is None or other.type is None)
        )

    # keep __hash__ from base type
    __hash__ = Hashable.__hash__

    def __repr__(self) -> str:
        if self.type is not None:
            return f"<Object id={self.id!r} type={self.type.__name__}>"
        return f"<Object id={self.id!r}>"

    @property
    def created_at(self) -> datetime.datetime:
        """:class:`datetime.datetime`: Returns the snowflake's creation time in UTC."""
        return utils.snowflake_time(self.id)
