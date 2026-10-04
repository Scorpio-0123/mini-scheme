"""内置库：spec §5 的全部标准过程，装进初始环境。

内置过程与特殊形式的区别只有一条（spec §5）：**内置过程的参数会先全部求值，
再调用**；特殊形式（``if``/``and``/... ）由 :mod:`src.evaluator` 按各自规则处理。
所以 ``and``/``or``/``quote`` 这类需要控制求值顺序的东西不在这里。

本模块按 spec §5 的分类组织：

- 算术：``+ - * / modulo quotient expt abs``
- 比较：``= < > <= >=``（链式）
- 布尔：``not``
- 列表：``cons car cdr list length append null? pair? list?``
- 谓词：``number? boolean? symbol? string? procedure? zero? even? odd? eq? equal?``
- 输出：``display newline``
"""

from __future__ import annotations

import warnings
from typing import Any, Callable

from .environment import BuiltinProcedure, Environment, bind_builtins
from .printer import describe_type, to_display_string
from .datatypes import (
    NIL,
    Pair,
    SchemeArityError,
    SchemeTypeError,
    is_number,
    is_pair,
    is_symbol,
    is_true,
    to_scheme_list,
)

# ---------------------------------------------------------------------------
# 小工具：参数检查与类型转换
# ---------------------------------------------------------------------------


def _require_number(value: Any, procedure: str) -> int | float:
    if not is_number(value):
        raise SchemeTypeError(
            f"{procedure} 的参数必须是数，实际得到 {describe_type(value)}："
            f"{to_display_string(value)}"
        )
    return value


def _require_integer(value: Any, procedure: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemeTypeError(
            f"{procedure} 的参数必须是整数，实际得到 {describe_type(value)}："
            f"{to_display_string(value)}"
        )
    return value


def _numbers(args: tuple, procedure: str) -> list:
    return [_require_number(arg, procedure) for arg in args]


def _quotient_int(numerator: int, denominator: int) -> int:
    """整数商，**向零截断**（spec §5：``(/ -7 2)`` -> ``-3``）。"""
    if denominator == 0:
        raise SchemeArityError("除数为 0")
    # Python 的 // 是向下取整（-7 // 2 == -4），所以先取绝对值再补符号。
    quotient = abs(numerator) // abs(denominator)
    return -quotient if (numerator < 0) != (denominator < 0) else quotient


def _truncating_modulo(numerator: int, denominator: int) -> int:
    """与向零截断整除配套的取模：``n = d * q + r``，``r`` 与 ``n`` 同号。"""
    return numerator - denominator * _quotient_int(numerator, denominator)


# ---------------------------------------------------------------------------
# 算术
# ---------------------------------------------------------------------------


def add(*args: Any) -> int | float:
    """``(+ 1 2 3)`` -> ``6``；``(+)`` -> ``0``。"""
    total: int | float = 0
    for number in _numbers(args, "+"):
        total += number
    return total


def subtract(*args: Any) -> int | float:
    """``(- 10 4 1)`` -> ``5``；单参数取反 ``(- 5)`` -> ``-5``。"""
    if not args:
        raise SchemeArityError("- 至少需要 1 个参数")
    numbers = _numbers(args, "-")
    if len(numbers) == 1:
        return -numbers[0]
    result = numbers[0]
    for number in numbers[1:]:
        result -= number
    return result


def multiply(*args: Any) -> int | float:
    """``(* 2 3 4)`` -> ``24``；``(*)`` -> ``1``。"""
    product: int | float = 1
    for number in _numbers(args, "*"):
        product *= number
    return product


def divide(*args: Any) -> int | float:
    """可变参数除法。

    - 全是整数 -> 整数商，向零截断：``(/ 7 2)`` -> ``3``，``(/ -7 2)`` -> ``-3``
    - 有一个是浮点 -> 浮点除法：``(/ 7.0 2)`` -> ``3.5``
    - 单参数 -> 取倒数（浮点）：``(/ 2)`` -> ``0.5``
    """
    if not args:
        raise SchemeArityError("/ 至少需要 1 个参数")
    numbers = _numbers(args, "/")
    if len(numbers) == 1:
        return 1 / numbers[0]
    if any(isinstance(number, float) for number in numbers):
        result = float(numbers[0])
        for number in numbers[1:]:
            result /= number
        return result
    result = numbers[0]
    for number in numbers[1:]:
        result = _quotient_int(result, number)
    return result


def modulo(numerator: Any, denominator: Any) -> int:
    """整数取模：``(modulo 17 5)`` -> ``2``。"""
    return _truncating_modulo(
        _require_integer(numerator, "modulo"), _require_integer(denominator, "modulo")
    )


def quotient(numerator: Any, denominator: Any) -> int:
    """整除商，向零截断：``(quotient -7 2)`` -> ``-3``。"""
    return _quotient_int(
        _require_integer(numerator, "quotient"),
        _require_integer(denominator, "quotient"),
    )


def expt(base: Any, power: Any) -> int | float:
    """乘方：``(expt 2 10)`` -> ``1024``。整数底与整数指数给出精确整数。"""
    base = _require_number(base, "expt")
    power = _require_number(power, "expt")
    if isinstance(base, int) and isinstance(power, int) and power >= 0:
        return base**power
    result = base**power
    if isinstance(result, complex):  # 例如 (expt -1 0.5)
        raise SchemeTypeError("expt 的结果不是实数")
    return result


def absolute(value: Any) -> int | float:
    """绝对值：``(abs (- 5 9))`` -> ``4``。"""
    return abs(_require_number(value, "abs"))


# ---------------------------------------------------------------------------
# 比较（链式）
# ---------------------------------------------------------------------------


def _compare_chain(args: tuple, operator: Callable[[Any, Any], bool], name: str) -> bool:
    """链式比较：相邻两两都成立才为真，``(< 2 3 4)`` -> ``#t``（spec §5）。"""
    if len(args) < 2:
        raise SchemeArityError(f"{name} 至少需要 2 个参数")
    with warnings.catch_warnings():
        # 语言层面/符号之间做大小比较只是数字练习（spec §11 未列为考点），
        # 这里压掉 DeprecationWarning，避免噪声打到 stdout 上。
        warnings.simplefilter("ignore", DeprecationWarning)
        for left, right in zip(args, args[1:]):
            if not operator(left, right):
                return False
    return True


def num_equal(*args: Any) -> bool:
    """``(= 1 1)`` -> ``#t``；注意 ``(= 1 1.0)`` 也为真（同为数、数值相等）。"""
    return _compare_chain(args, lambda a, b: a == b, "=")


def less_than(*args: Any) -> bool:
    return _compare_chain(args, lambda a, b: a < b, "<")


def greater_than(*args: Any) -> bool:
    return _compare_chain(args, lambda a, b: a > b, ">")


def less_or_equal(*args: Any) -> bool:
    return _compare_chain(args, lambda a, b: a <= b, "<=")


def greater_or_equal(*args: Any) -> bool:
    return _compare_chain(args, lambda a, b: a >= b, ">=")


# ---------------------------------------------------------------------------
# 布尔
# ---------------------------------------------------------------------------


def logical_not(value: Any) -> bool:
    """取反：``(not #f)`` -> ``#t``；``(not 0)`` -> ``#f``（只有 ``#f`` 是假）。"""
    return not is_true(value)


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------


def cons(first: Any, second: Any) -> Pair:
    """构造点对：``(cons 1 2)`` -> ``(1 . 2)``。"""
    return Pair(first, second)


def car(pair: Any) -> Any:
    """取点对第一项：``(car '(1 2 3))`` -> ``1``。"""
    if not is_pair(pair):
        raise SchemeTypeError(
            f"car 的参数必须是点对，实际得到 {describe_type(pair)}"
        )
    return pair.car


def cdr(pair: Any) -> Any:
    """取点对第二项：``(cdr '(1 2 3))`` -> ``(2 3)``。"""
    if not is_pair(pair):
        raise SchemeTypeError(
            f"cdr 的参数必须是点对，实际得到 {describe_type(pair)}"
        )
    return pair.cdr


def make_list(*args: Any) -> Any:
    """打包成列表：``(list 1 2 3)`` -> ``(1 2 3)``。"""
    return to_scheme_list(args)


def length(value: Any) -> int:
    """列表长度：``(length '(a b c d))`` -> ``4``。"""
    count = 0
    cursor = value
    while is_pair(cursor):
        count += 1
        cursor = cursor.cdr
    if cursor is not NIL:
        raise SchemeTypeError("length 的参数必须是真列表")
    return count


def append(*lists: Any) -> Any:
    """拼接若干列表：``(append '(1 2) '(3 4))`` -> ``(1 2 3 4)``。

    最后一个参数可以是任意值（成为结果链的末端），前面的必须都是真列表。
    """
    if not lists:
        return NIL
    result: Any = lists[-1]
    for value in reversed(lists[:-1]):
        tail = result
        result = _copy_list_onto(value, tail)
    return result


def _copy_list_onto(value: Any, tail: Any) -> Any:
    """把真列表 ``value`` 浅拷贝一份，末端接上 ``tail``。"""
    items: list[Any] = []
    cursor = value
    while is_pair(cursor):
        items.append(cursor.car)
        cursor = cursor.cdr
    if cursor is not NIL:
        raise SchemeTypeError("append 的参数（除最后一个）必须是真列表")
    result = tail
    for item in reversed(items):
        result = Pair(item, result)
    return result


def is_null(value: Any) -> bool:
    """是否空表：``(null? '())`` -> ``#t``。"""
    return value is NIL


def is_pair_predicate(value: Any) -> bool:
    """是否点对（非空）：``(pair? '(1 2))`` -> ``#t``，``(pair? '())`` -> ``#f``。"""
    return is_pair(value)


def is_list(value: Any) -> bool:
    """是否真列表：``(list? (cons 1 2))`` -> ``#f``。"""
    cursor = value
    while True:
        if cursor is NIL:
            return True
        if not is_pair(cursor):
            return False
        cursor = cursor.cdr


# ---------------------------------------------------------------------------
# 谓词
# ---------------------------------------------------------------------------


def is_number_predicate(value: Any) -> bool:
    return is_number(value)


def is_boolean_predicate(value: Any) -> bool:
    return isinstance(value, bool)


def is_symbol_predicate(value: Any) -> bool:
    return is_symbol(value)


def is_string_predicate(value: Any) -> bool:
    return isinstance(value, str) and not is_symbol(value)


def is_procedure_predicate(value: Any) -> bool:
    """是否过程：``(procedure? car)`` -> ``#t``，``(procedure? 1)`` -> ``#f``。

    "是不是过程"由 :class:`src.evaluator.Procedure` 协议统一回答：内置过程和
    用户闭包都实现 ``apply``，所以这里用鸭子类型判断，不必彼此 import 成环。
    """
    return callable(getattr(value, "apply", None))


def is_zero(value: Any) -> bool:
    return _require_number(value, "zero?") == 0


def is_even(value: Any) -> bool:
    return _require_integer(value, "even?") % 2 == 0


def is_odd(value: Any) -> bool:
    return _require_integer(value, "odd?") % 2 != 0


def eq(left: Any, right: Any) -> bool:
    """同一性比较（spec §5）。

    - 数、符号、布尔按值比较；
    - 空表 ``'()`` 是单例，所以 ``(eq? '() '())`` -> ``#t``；
    - 列表等复合数据比"是不是同一个对象"，所以 ``(eq? '(1) '(1))`` -> ``#f``。
    """
    if left is right:
        return True  # NIL 单例、同一个 Pair 对象等
    if is_number(left) or is_number(right):
        # 两边都是数才算相等；先比类型族再比值，避免 True == 1（spec §11）。
        return is_number(left) and is_number(right) and left == right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if is_symbol(left) and is_symbol(right):
        return str(left) == str(right)
    if isinstance(left, str) or isinstance(right, str):
        # 字符串与符号是不同类型的值（spec §11），字符串按值比较。
        return (
            isinstance(left, str)
            and isinstance(right, str)
            and not is_symbol(left)
            and not is_symbol(right)
            and left == right
        )
    return False


def equal(left: Any, right: Any) -> bool:
    """结构相等（逐层比较）：``(equal? '(1 2 3) (list 1 2 3))`` -> ``#t``。"""
    if eq(left, right):
        return True
    if is_pair(left) and is_pair(right):
        return equal(left.car, right.car) and equal(left.cdr, right.cdr)
    if is_number(left) and is_number(right):
        return left == right
    return False


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def display(value: Any) -> None:
    """打印一个值（字符串不带引号），不换行。返回 ``None`` -> 顶层不打印。"""
    print(to_display_string(value), end="")
    return None


def newline() -> None:
    """输出一个换行。返回 ``None`` -> 顶层不打印。"""
    print()
    return None


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------

#: spec §5 的全部内置过程。名字 -> 过程（含参数个数约束）。
BUILTIN_PROCEDURES: dict[str, BuiltinProcedure] = {
    # 算术
    "+": BuiltinProcedure("+", add),
    "-": BuiltinProcedure("-", subtract, min_args=1),
    "*": BuiltinProcedure("*", multiply),
    "/": BuiltinProcedure("/", divide, min_args=1),
    "modulo": BuiltinProcedure("modulo", modulo, min_args=2, max_args=2),
    "quotient": BuiltinProcedure("quotient", quotient, min_args=2, max_args=2),
    "expt": BuiltinProcedure("expt", expt, min_args=2, max_args=2),
    "abs": BuiltinProcedure("abs", absolute, min_args=1, max_args=1),
    # 比较（至少 2 个参数才能构成"链"）
    "=": BuiltinProcedure("=", num_equal, min_args=2),
    "<": BuiltinProcedure("<", less_than, min_args=2),
    ">": BuiltinProcedure(">", greater_than, min_args=2),
    "<=": BuiltinProcedure("<=", less_or_equal, min_args=2),
    ">=": BuiltinProcedure(">=", greater_or_equal, min_args=2),
    # 布尔
    "not": BuiltinProcedure("not", logical_not, min_args=1, max_args=1),
    # 列表
    "cons": BuiltinProcedure("cons", cons, min_args=2, max_args=2),
    "car": BuiltinProcedure("car", car, min_args=1, max_args=1),
    "cdr": BuiltinProcedure("cdr", cdr, min_args=1, max_args=1),
    "list": BuiltinProcedure("list", make_list),
    "length": BuiltinProcedure("length", length, min_args=1, max_args=1),
    "append": BuiltinProcedure("append", append),
    "null?": BuiltinProcedure("null?", is_null, min_args=1, max_args=1),
    "pair?": BuiltinProcedure("pair?", is_pair_predicate, min_args=1, max_args=1),
    "list?": BuiltinProcedure("list?", is_list, min_args=1, max_args=1),
    # 谓词
    "number?": BuiltinProcedure("number?", is_number_predicate, min_args=1, max_args=1),
    "boolean?": BuiltinProcedure("boolean?", is_boolean_predicate, min_args=1, max_args=1),
    "symbol?": BuiltinProcedure("symbol?", is_symbol_predicate, min_args=1, max_args=1),
    "string?": BuiltinProcedure("string?", is_string_predicate, min_args=1, max_args=1),
    "procedure?": BuiltinProcedure("procedure?", is_procedure_predicate, min_args=1, max_args=1),
    "zero?": BuiltinProcedure("zero?", is_zero, min_args=1, max_args=1),
    "even?": BuiltinProcedure("even?", is_even, min_args=1, max_args=1),
    "odd?": BuiltinProcedure("odd?", is_odd, min_args=1, max_args=1),
    "eq?": BuiltinProcedure("eq?", eq, min_args=2, max_args=2),
    "equal?": BuiltinProcedure("equal?", equal, min_args=2, max_args=2),
    # 输出
    "display": BuiltinProcedure("display", display, min_args=1, max_args=1),
    "newline": BuiltinProcedure("newline", newline, min_args=0, max_args=0),
}


def make_global_environment() -> Environment:
    """创建初始（全局）环境，并装入 spec §5 的全部内置过程。"""
    environment = Environment()
    bind_builtins(environment, BUILTIN_PROCEDURES)
    return environment
