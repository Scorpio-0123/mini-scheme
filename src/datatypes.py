"""mini-Scheme 的数据类型。

本模块只关心"值长什么样"，不涉及词法、语法或求值，因此可以被其它模块安全地
导入而不产生循环依赖。

注意：本文件**不能**叫 ``types.py``。运行时 ``src/`` 目录会被放进 ``sys.path``
（``python src/main.py`` 的行为），那样就会盖住标准库的 ``types`` 模块，导致
标准库内部的 ``from types import ...`` 全部报错。

约定（读者第一次看这段代码时请先记住）:

- 整数 / 浮点            -> Python 的 ``int`` / ``float``
- 布尔                  -> Python 的 ``bool``（注意 ``bool`` 是 ``int`` 的子类，
                            所以判断顺序永远是"先 bool 后 int"，见 ``is_number``）
- 字符串                -> Python 的 ``str``
- 符号                  -> :class:`Symbol`（``str`` 的子类，但语义完全不同，
                            绝不能用 ``==`` 直接和字符串比较）
- 真列表 / 点对         -> :class:`Pair` 组成的链
- 空表 ``()``           -> :data:`NIL` 单例
- 无值（如 display 的结果） -> Python 的 ``None``
"""

from __future__ import annotations

from typing import Any, Iterator


class Symbol(str):
    """一个 Scheme 符号，例如 ``foo``、``+``、``x1``。

    做成 ``str`` 的子类是为了方便调试与哈希，但符号和字符串是两种不同的值：
    ``(eq? 'a "a")`` 必须为假（见 spec §11）。因此比较符号时请用
    :func:`is_symbol` 先确认类型，或者直接比较 ``Symbol`` 与 ``Symbol``。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"Symbol({str.__repr__(self)})"


class Pair:
    """一个点对（cons cell）：``car`` 是第一项，``cdr`` 是第二项。

    列表 ``(1 2 3)`` 就是这样一条链::

        Pair(1, Pair(2, Pair(3, NIL)))

    ``cdr`` 不是 ``Pair`` 也不是 ``NIL`` 时，就是一个"不真"的点对，
    打印成 ``(1 . 2)``（见 spec §6）。
    """

    __slots__ = ("car", "cdr")

    def __init__(self, car: Any, cdr: Any) -> None:
        self.car = car
        self.cdr = cdr

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"Pair({self.car!r}, {self.cdr!r})"


class _Nil:
    """空表 ``()`` 的单例类型。

    ``eq?`` 对 ``'()`` 必须为真，所以全局只能有一个实例；同时它**不是**
    Python 的 ``None``，因为 ``None`` 已经被用来表示"无值/不打印"（spec §2）。
    """

    __slots__ = ()

    _instance: "_Nil | None" = None

    def __new__(cls) -> "_Nil":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NIL"

    def __bool__(self) -> bool:
        # 只有 #f 为假，() 是真值（spec §4.4）。显式给出以免将来误用真值判断。
        return True


#: 空表的唯一实例。请始终与它做 ``is`` 比较，不要用 ``==``。
NIL = _Nil()


def is_symbol(value: Any) -> bool:
    """``value`` 是不是符号。"""
    return isinstance(value, Symbol)


def is_string(value: Any) -> bool:
    """``value`` 是不是字符串（符号不算）。"""
    return isinstance(value, str) and not isinstance(value, Symbol)


def is_boolean(value: Any) -> bool:
    """``value`` 是不是 ``#t`` / ``#f``。"""
    return isinstance(value, bool)


def is_number(value: Any) -> bool:
    """``value`` 是不是数（布尔不算，因为 Python 里 ``True == 1``）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_pair(value: Any) -> bool:
    """``value`` 是不是点对（空表不算，见 spec §5 的 ``pair?``）。"""
    return isinstance(value, Pair)


def is_empty(value: Any) -> bool:
    """``value`` 是不是空表 ``()``。"""
    return value is NIL


def is_true(value: Any) -> bool:
    """Scheme 的真值判断：**只有 ``#f`` 是假**，``0``、``()``、``""`` 都是真。"""
    return value is not False


def cons(car: Any, cdr: Any) -> Pair:
    """构造一个点对，等价于内置的 ``cons``。"""
    return Pair(car, cdr)


def to_scheme_list(items: Any) -> Any:
    """把 Python 可迭代对象转换成 Scheme 列表（末端的 ``cdr`` 是 ``NIL``）。"""
    result: Any = NIL
    materialised = list(items)
    for item in reversed(materialised):
        result = Pair(item, result)
    return result


def from_scheme_list(value: Any, *, name: str = "列表") -> list:
    """把 Scheme 列表拆成 Python ``list``。

    遇到不真列表（例如 ``(1 . 2)``）时抛出 :class:`SchemeTypeError`；需要更宽松
    的行为时请直接遍历 :class:`Pair` 链。
    """
    items: list = []
    cursor = value
    while isinstance(cursor, Pair):
        items.append(cursor.car)
        cursor = cursor.cdr
    if cursor is not NIL:
        raise SchemeTypeError(f"{name}必须是真列表，实际得到 {cursor!r}")
    return items


def iter_list(value: Any) -> Iterator[Any]:
    """遍历一条 ``Pair`` 链（不含末端的 ``NIL``）。"""
    cursor = value
    while isinstance(cursor, Pair):
        yield cursor.car
        cursor = cursor.cdr


class SchemeError(Exception):
    """解释器内部错误的基类。

    出错时的行为按 spec §10 属于"未定义"，测试不会故意触发；这里集中定义是为了
    让入口能统一、友好地报告问题，而不是抛出一个裸的 ``AttributeError``。
    """


class SchemeSyntaxError(SchemeError):
    """词法/语法错误（括号不配对、字符串未闭合等）。"""


class SchemeTypeError(SchemeError):
    """类型错误（把非过程当函数调用、对非数做算术等）。"""


class SchemeNameError(SchemeError):
    """引用了未绑定的名字。"""


class SchemeArityError(SchemeError):
    """实参个数不对。"""
