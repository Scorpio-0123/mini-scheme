"""打印：值 -> 文本。

流水线的最后一站，只管"值长什么样"（spec §8），不参与求值。
两种模式的区别来自 spec §5 的 ``display``：

- :func:`to_write_string`：``write`` 风格，字符串**带**引号、内部特殊字符转义。
  顶层求值结果、列表/点对内部的字符串都用它。
- :func:`to_display_string`：``display`` 风格，字符串**不带**引号。

列表的两种形态（spec §6）：

- 真列表 ``(1 2 3)``
- 点对 ``(1 . 2)``，以及混合形态 ``(1 2 . 3)``
"""

from __future__ import annotations

from typing import Any

from .datatypes import NIL, Pair, Symbol

#: 过程（内置过程与用户闭包）的统一打印形式；spec §8 说明测试不依赖确切格式。
PROCEDURE_TEXT = "#<procedure>"

_BOOL_TEXT = {True: "#t", False: "#f"}

_STRING_ESCAPES = (
    ("\\", "\\\\"),
    ('"', '\\"'),
    ("\n", "\\n"),
    ("\t", "\\t"),
    ("\r", "\\r"),
)


def to_write_string(value: Any) -> str:
    """把一个值渲染成"可被读回"的文本（字符串带引号）。"""
    return _render(value, quote_strings=True)


def to_display_string(value: Any) -> str:
    """把一个值渲染成"给人看"的文本（字符串不带引号），供 ``display`` 使用。"""
    return _render(value, quote_strings=False)


def _render(value: Any, *, quote_strings: bool) -> str:
    if value is None:
        # None 表示"无值"（如 display 的结果）。正常流程不会打印它，
        # 这里给一个可读的占位，纯粹为了方便调试。
        return "#<void>"
    if value is True or value is False:
        return _BOOL_TEXT[value]
    if isinstance(value, Symbol):
        return str(value)
    if isinstance(value, str):
        return _render_string(value) if quote_strings else value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _render_float(value)
    if value is NIL:
        return "()"
    if isinstance(value, Pair):
        return _render_pair(value, quote_strings=quote_strings)
    return PROCEDURE_TEXT


def _render_string(text: str) -> str:
    escaped = text
    for raw, replacement in _STRING_ESCAPES:
        escaped = escaped.replace(raw, replacement)
    return f'"{escaped}"'


def _render_float(value: float) -> str:
    """浮点按 Python 的默认写法输出，例如 ``0.5``（spec §8）。"""
    if value != value:  # NaN
        return "+nan.0"
    if value == float("inf"):
        return "+inf.0"
    if value == float("-inf"):
        return "-inf.0"
    if value.is_integer() and abs(value) < 1e16:
        # 避免把 3.0 打成 "3"，那样就读回整数了；保留小数点以声明这是浮点。
        return f"{value:.1f}"
    return repr(value)


def _render_pair(pair: Pair, *, quote_strings: bool) -> str:
    parts: list[str] = []
    cursor: Any = pair
    while isinstance(cursor, Pair):
        parts.append(_render(cursor.car, quote_strings=quote_strings))
        cursor = cursor.cdr
    if cursor is NIL:
        return "(" + " ".join(parts) + ")"
    # 不真列表：末段用点号表示（spec §6）。
    tail = _render(cursor, quote_strings=quote_strings)
    return "(" + " ".join(parts) + " . " + tail + ")"


def describe_type(value: Any) -> str:
    """给错误信息用的人类可读类型名。"""
    if value is None:
        return "无值"
    if isinstance(value, bool):
        return "布尔"
    if isinstance(value, Symbol):
        return "符号"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, int):
        return "整数"
    if isinstance(value, float):
        return "浮点"
    if value is NIL:
        return "空表"
    if isinstance(value, Pair):
        return "点对"
    return "过程"
