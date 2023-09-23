# SPDX-License-Identifier: MIT

from datetime import datetime, timezone

import pytest

import disnake
from disnake import Object

from .helpers import create_snowflake

snowflake = 881536165478499999  # date/time of first commit


def test_init() -> None:
    with pytest.raises(
        TypeError, match=r"id parameter must be convertable to int not <class 'str'>"
    ):
        Object("hi")


def test_compare() -> None:
    assert Object(42) == Object(42)
    assert Object(42) != Object(43)


def test_hash() -> None:
    assert hash(Object(snowflake)) == 210174600000


def test_created_at() -> None:
    assert Object(snowflake).created_at == datetime(2021, 8, 29, 13, 50, 0, tzinfo=timezone.utc)


def test_no_type() -> None:
    assert Object(1).type is None


def test_type() -> None:
    assert Object(1, type=disnake.Role).type is disnake.Role


def _assert_all_equal(a, b) -> None:
    # might look weird, but we want to explicitly test __eq__ and __ne__ (and in both directions) here
    assert a == b
    assert b == a
    assert not (a != b)
    assert not (b != a)


def _assert_all_not_equal(a, b) -> None:
    assert a != b
    assert b != a
    assert not (a == b)
    assert not (b == a)


def test_equal_simple() -> None:
    _assert_all_equal(Object(123), Object(123))


def test_not_equal_simple() -> None:
    _assert_all_not_equal(Object(123), Object(456))


def test_one_type() -> None:
    _assert_all_equal(Object(123), Object(123, type=disnake.Role))
    _assert_all_not_equal(Object(123), Object(456, type=disnake.Role))


def test_model_compare() -> None:
    _assert_all_not_equal(Object(123), create_snowflake(disnake.Role, 123))
    _assert_all_not_equal(Object(123, type=disnake.Role), create_snowflake(disnake.Role, 123))


def test_two_types_same() -> None:
    _assert_all_equal(Object(123, type=disnake.Role), Object(123, type=disnake.Role))
    _assert_all_not_equal(Object(123, type=disnake.Role), Object(456, type=disnake.Role))


def test_two_types_diff() -> None:
    _assert_all_not_equal(Object(123, type=disnake.Role), Object(123, type=disnake.User))
    _assert_all_not_equal(Object(123, type=disnake.Role), Object(456, type=disnake.User))


def test_subtype() -> None:
    _assert_all_not_equal(
        Object(123, type=disnake.abc.GuildChannel), Object(123, type=disnake.TextChannel)
    )
