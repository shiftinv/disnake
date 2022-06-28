import contextlib
from typing import Any, Iterator, Type

import pytest
from typing_extensions import assert_type

from disnake import ui
from disnake.ui.button import V_co
from disnake.ui.item import ItemT


@contextlib.contextmanager
def create_callback(item_type: Type[ItemT]) -> Iterator["ui.item.ItemCallbackType[ItemT]"]:
    async def callback(self, item, inter):
        pytest.fail("callback should not be invoked")

    yield callback

    # ensure instantiation works
    assert callback.__discord_ui_model_type__(**callback.__discord_ui_model_kwargs__)


class CustomView(ui.View):
    pass


class _CustomButton(ui.Button[V_co]):
    def __init__(self, *, param: float = 42.0):
        pass


class TestDecorator:
    def test_default(self) -> None:
        with create_callback(ui.Button[CustomView]) as func:
            res = ui.button(custom_id="123")(func)
            assert_type(res, ui.item.DecoratedItem[ui.Button[CustomView]])

            assert func.__discord_ui_model_type__ is ui.Button
            assert func.__discord_ui_model_kwargs__ == {"custom_id": "123"}

        with create_callback(ui.Select[CustomView]) as func:
            res = ui.select(custom_id="123")(func)
            assert_type(res, ui.item.DecoratedItem[ui.Select[CustomView]])

            assert func.__discord_ui_model_type__ is ui.Select
            assert func.__discord_ui_model_kwargs__ == {"custom_id": "123"}

    # from here on out we're only testing the button decorator,
    # as @ui.select works identically

    @pytest.mark.parametrize("cls", [_CustomButton, _CustomButton[Any]])
    def test_cls(self, cls: Type[_CustomButton[Any]]) -> None:
        with create_callback(cls) as func:
            res = ui.button(cls=cls, param=1337)(func)
            assert_type(res, ui.item.DecoratedItem[cls])

            # should strip to origin type
            assert func.__discord_ui_model_type__ is _CustomButton
            assert func.__discord_ui_model_kwargs__ == {"param": 1337}

    # typing-only check
    def _test_typing_cls(self) -> None:
        ui.button(
            cls=_CustomButton,
            this_should_not_work="h",  # type: ignore
        )

    @pytest.mark.parametrize("cls", [123, int, ui.Select])
    def test_cls_invalid(self, cls) -> None:
        with pytest.raises(TypeError, match=r"cls argument must be"):
            ui.button(cls=cls)  # type: ignore
