"""求值器：表达式 -> 值（解释器的心脏）。

核心是两个**互相递归**的函数：

- :func:`evaluate`：求值一个表达式。符号 -> 查环境；字面量 -> 原样返回；
  括号表达式 -> 特殊形式走各自规则，其余当成函数调用（先求值操作符与全部实参，
  再交给 :func:`apply_procedure`）。
- :func:`apply_procedure`：调用一个过程。内置过程直接调用；用户闭包则新建一层
  环境把实参绑到形参上（外层指向函数**定义时**的环境，这是词法作用域的关键），
  再回到 :func:`evaluate` 求值函数体。

``evaluate`` 遇到函数调用就调 ``apply_procedure``，后者执行函数体又调回
``evaluate``——想通这个循环，解释器就成了一半。

spec §4 的特殊形式已全部实现：``quote`` / ``if`` / ``cond`` / ``and`` / ``or`` /
``define`` / ``lambda`` / ``let`` / ``begin``。用户函数可以递归（``define``
的函数体内能看见自己的名字）、可以闭包（``lambda`` 捕获定义处环境）。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .environment import Environment
from .printer import describe_type, to_display_string
from .datatypes import (
    NIL,
    Pair,
    SchemeArityError,
    SchemeSyntaxError,
    SchemeTypeError,
    Symbol,
    is_true,
)

#: ``(quote x)`` 的等价写法。
QUOTE = Symbol("quote")

#: ``cond`` 的兜底子句关键字。
ELSE = Symbol("else")


class Procedure:
    """"过程"的统一接口。

    :class:`src.environment.BuiltinProcedure` 与 :class:`UserProcedure` 都实现
    ``apply(args)``，求值器只依赖这个约定，不需要知道具体是哪种过程。
    """

    def apply(self, args: list[Any]) -> Any:  # pragma: no cover - 接口声明
        raise NotImplementedError


class UserProcedure(Procedure):
    """用户定义的函数（``lambda`` 产生的闭包）。

    ``parameters`` 是形参名列表，``body`` 是函数体表达式列表（按 ``begin``
    语义顺序求值），``environment`` 是**定义时**捕获的环境。参数个数固定
    （spec §10：不支持可变参数 lambda）。
    """

    __slots__ = ("parameters", "body", "environment", "name")

    def __init__(
        self,
        parameters: list[Symbol],
        body: list[Any],
        environment: Environment,
        name: str = "lambda",
    ) -> None:
        self.parameters = parameters
        self.body = body
        self.environment = environment
        self.name = name

    def apply(self, args: list[Any]) -> Any:
        """新建一层环境绑定实参，然后在其中求值函数体。"""
        if len(args) != len(self.parameters):
            raise SchemeArityError(
                f"{self.name} 需要 {len(self.parameters)} 个参数，"
                f"实际给了 {len(args)} 个"
            )
        call_environment = Environment(parent=self.environment)
        call_environment.define_all(self.parameters, args)
        return evaluate_sequence(self.body, call_environment)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"#<procedure {self.name}>"


# ---------------------------------------------------------------------------
# 求值：表达式 -> 值
# ---------------------------------------------------------------------------


def evaluate(expression: Any, environment: Environment) -> Any:
    """求值一个表达式，返回对应的值。"""
    if isinstance(expression, Symbol):
        return environment.lookup(expression)
    if isinstance(expression, Pair):
        return _evaluate_form(expression, environment)
    # 整数、浮点、布尔、字符串、空表等"基本值"原样返回（spec §1 铁律 1）。
    return expression


def _evaluate_form(expression: Pair, environment: Environment) -> Any:
    """求值一个括号表达式：先看是不是特殊形式，否则按函数调用处理。"""
    operator = expression.car
    if isinstance(operator, Symbol):
        form = SPECIAL_FORMS.get(str(operator))
        if form is not None:
            arguments = _list_to_python(expression.cdr, f"{operator} 的参数")
            return form(arguments, environment, expression)
    # 普通函数调用（spec §9）：先求值操作符，再从左到右求值全部实参。
    procedure = evaluate(operator, environment)
    arguments = [evaluate(argument, environment) for argument in _iter_list(expression.cdr)]
    return apply_procedure(procedure, arguments)


def evaluate_sequence(expressions: Iterable[Any], environment: Environment) -> Any:
    """按 ``begin`` 语义依次求值，返回最后一个的结果；空序列返回 ``None``。"""
    result: Any = None
    for expression in expressions:
        result = evaluate(expression, environment)
    return result


def evaluate_program(expressions: Sequence[Any], environment: Environment) -> list[Any]:
    """求值一串顶层表达式，返回每个表达式的结果（``None`` 表示"无值"）。"""
    return [evaluate(expression, environment) for expression in expressions]


# ---------------------------------------------------------------------------
# 调用：过程 + 实参 -> 值
# ---------------------------------------------------------------------------


def apply_procedure(procedure: Any, args: list[Any]) -> Any:
    """调用一个过程。内置过程与用户闭包都走 ``apply``。"""
    apply_method = getattr(procedure, "apply", None)
    if not callable(apply_method):
        raise SchemeTypeError(
            f"{to_display_string(procedure)} 不是过程，无法调用"
            f"（它的类型是{describe_type(procedure)}；"
            f"检查一下语序，是不是把中缀写成了前缀？）"
        )
    return apply_method(args)


# ---------------------------------------------------------------------------
# 特殊形式（spec §4）
#
# 每个函数签名统一为 (arguments, environment, whole) -> 值，其中 ``arguments``
# 已经是 Python list（调用方负责把语法树上的 Pair 链拆开）。
# ---------------------------------------------------------------------------


def _special_quote(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(quote 数据)``：**不求值**，原样返回（spec §4.1）。"""
    _expect_arity("quote", arguments, 1, whole)
    return arguments[0]


def _special_if(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(if 测试 真分支 假分支?)``：只求值一个分支（spec §4.2）。"""
    _expect_arity("if", arguments, 2, whole, maximum=3)
    if is_true(evaluate(arguments[0], environment)):
        return evaluate(arguments[1], environment)
    if len(arguments) == 3:
        return evaluate(arguments[2], environment)
    # 省略假分支且测试为假 -> 无值（顶层不打印）。
    return None


def _special_cond(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(cond (测试 表达式...)... (else 表达式...))``（spec §4.3）。"""
    for clause in arguments:
        if not isinstance(clause, Pair) and clause is not NIL:
            raise SchemeSyntaxError("cond 的每个子句必须是列表")
        parts = _list_to_python(clause, "cond 子句")
        if not parts:
            raise SchemeSyntaxError("cond 的子句不能为空")
        test = parts[0]
        body = parts[1:]
        if isinstance(test, Symbol) and str(test) == "else":
            return evaluate_sequence(body, environment)
        test_value = evaluate(test, environment)
        if is_true(test_value):
            # 子句里没有表达式时，返回测试值本身。
            return evaluate_sequence(body, environment) if body else test_value
    return None


def _special_and(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(and e1 e2 ...)``：短路，遇 ``#f`` 立即返回（spec §4.4）。"""
    result: Any = True
    for argument in arguments:
        result = evaluate(argument, environment)
        if not is_true(result):
            return result  # 立刻返回 #f，后面的表达式不执行
    return result


def _special_or(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(or e1 e2 ...)``：短路，遇真值立即返回（spec §4.4）。"""
    result: Any = False
    for argument in arguments:
        result = evaluate(argument, environment)
        if is_true(result):
            return result  # 立刻返回该真值，后面的表达式不执行
    return result


def _special_begin(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(begin e1 e2 ...)``：顺序求值，返回最后一个（spec §4.8）。"""
    return evaluate_sequence(arguments, environment)


def _special_define(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(define 名 表达式)`` / ``(define (函数名 参数...) 体...)``（spec §4.5）。

    求值顺序：**先求值右侧的表达式，再在当前环境绑定**。返回被定义的符号名
    （顶层会打印出来，见 spec §11"输出比预期多一行"那一行）。

    第二种写法是"定义函数"的简写，等价于
    ``(define 函数名 (lambda (参数...) 体...))``。
    """
    _expect_arity("define", arguments, 2, whole)
    target = arguments[0]

    if isinstance(target, Symbol):
        # (define 名 表达式)
        if len(arguments) != 2:
            raise SchemeSyntaxError(
                f"(define 名 表达式) 只能有一个表达式，实际给了 {len(arguments) - 1} 个"
            )
        value = evaluate(arguments[1], environment)
        environment.define(target, value)
        return target

    if isinstance(target, Pair):
        # (define (函数名 参数...) 体...)，展开成 (define 函数名 (lambda ...))
        function_name = target.car
        if not isinstance(function_name, Symbol):
            raise SchemeSyntaxError(
                f"define 的函数名必须是符号，实际是"
                f"{to_display_string(function_name)}"
            )
        parameters = _parse_parameters(target.cdr, f"define {function_name}")
        body = _parse_body(arguments[1:], f"define {function_name}")
        procedure = UserProcedure(parameters, body, environment, name=str(function_name))
        environment.define(function_name, procedure)
        return function_name

    raise SchemeSyntaxError(
        f"define 的第一个参数必须是符号或 (函数名 参数...) 形式，实际是"
        f"{to_display_string(target)}"
    )


def _special_lambda(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(lambda (参数...) 体...)``：产生闭包（spec §4.6）。

    求值顺序：**函数体此时不求值**，只把参数名、函数体和**当前环境**打包起来，
    等以后被调用时才求值。捕获的就是这里传进来的 ``environment``——它指向定义
    处的作用域，所以叫"闭包"（spec §9：词法作用域）。
    """
    _expect_arity("lambda", arguments, 2, whole)
    parameters = _parse_parameters(arguments[0], "lambda")
    body = _parse_body(arguments[1:], "lambda")
    return UserProcedure(parameters, body, environment)


def _special_let(arguments: list[Any], environment: Environment, whole: Pair) -> Any:
    """``(let ((名 表达式)...) 体...)``：局部变量（spec §4.7）。

    求值顺序：**并行绑定**——先把每个绑定表达式都在**外层**环境求值完（此刻新
    名字还不可见，绑定之间互不可见），再新建一层环境把所有名字一次装好，最后在
    新环境里按 ``begin`` 语义求值函数体。

    spec §11 特别点名：串行绑定（边求值边绑定到新环境）是常见错法。
    """
    _expect_arity("let", arguments, 1, whole)
    names, values = _evaluate_bindings(arguments[0], environment)

    local_environment = environment.child()
    local_environment.define_all(names, values)
    return evaluate_sequence(arguments[1:], local_environment)


#: 特殊形式分发表：名字 -> 处理函数。表里没有的名字按普通函数调用处理。
SPECIAL_FORMS = {
    "quote": _special_quote,
    "if": _special_if,
    "cond": _special_cond,
    "and": _special_and,
    "or": _special_or,
    "begin": _special_begin,
    "define": _special_define,
    "lambda": _special_lambda,
    "let": _special_let,
}


# ---------------------------------------------------------------------------
# 语法树小工具
# ---------------------------------------------------------------------------


def _iter_list(value: Any) -> Iterable[Any]:
    """遍历一条 ``Pair`` 链。遇到不真列表（点对语法）时报语法错误。"""
    cursor = value
    while isinstance(cursor, Pair):
        yield cursor.car
        cursor = cursor.cdr
    if cursor is not NIL:
        raise SchemeSyntaxError(
            f"这里应该是真列表，但在 {to_display_string(cursor)} 处提前结束了"
        )


def _list_to_python(value: Any, what: str) -> list[Any]:
    """把 ``Pair`` 链转成 Python ``list``，顺便给出可读的报错信息。"""
    items: list[Any] = []
    cursor = value
    while isinstance(cursor, Pair):
        items.append(cursor.car)
        cursor = cursor.cdr
    if cursor is not NIL:
        raise SchemeSyntaxError(f"{what}必须是真列表")
    return items


def _expect_arity(
    form: str,
    arguments: list[Any],
    minimum: int,
    whole: Pair,
    maximum: int | None = None,
) -> None:
    """检查特殊形式的参数个数，给出明确的报错。"""
    count = len(arguments)
    if count < minimum:
        raise SchemeSyntaxError(
            f"{form} 至少需要 {minimum} 个参数，实际给了 {count} 个"
        )
    if maximum is not None and count > maximum:
        raise SchemeSyntaxError(
            f"{form} 最多接受 {maximum} 个参数，实际给了 {count} 个"
        )


def symbol_is(expression: Any, name: str) -> bool:
    """``expression`` 是不是名为 ``name`` 的符号（大小写敏感）。"""
    return isinstance(expression, Symbol) and str(expression) == name


# ---------------------------------------------------------------------------
# define / lambda / let 共用的语法检查
# ---------------------------------------------------------------------------


def _parse_parameters(formals: Any, what: str) -> list[Symbol]:
    """检查参数表 ``(x y z)``，返回参数名列表。

    spec §10 不支持可变参数 lambda，所以这里要求一个**真列表**，元素全是符号。
    重名参数（如 ``(lambda (x x) ...)``）不报错：后一个绑定覆盖前一个，
    与内置/验收用例对 ``let`` 的期望一致，宽松处理比报错更安全。
    """
    names = _list_to_python(formals, f"{what} 的参数表")
    for name in names:
        if not isinstance(name, Symbol):
            raise SchemeSyntaxError(
                f"{what} 的参数名必须是符号，实际是{to_display_string(name)}"
            )
    return names


def _parse_body(expressions: list[Any], what: str) -> list[Any]:
    """检查函数体至少有一个表达式，返回函数体列表。"""
    if not expressions:
        raise SchemeSyntaxError(f"{what} 的函数体不能为空")
    return expressions


def _evaluate_bindings(bindings: Any, environment: Environment) -> tuple[list[Symbol], list[Any]]:
    """求值 ``let`` 的绑定串 ``((名1 表达式1) (名2 表达式2))``。

    返回 (名字列表, 值列表)。**所有表达式都在传进来的（外层）环境求值**，
    这就是"并行绑定"：第二个绑定看不见第一个绑定引入的名字。

    重名绑定（如 ``(let ((x 1) (x 2)) x)``）按"后一个生效"处理：``define_all``
    顺序绑定，后面的自然覆盖前面的。
    """
    if not isinstance(bindings, Pair) and bindings is not NIL:
        raise SchemeSyntaxError(
            f"let 的绑定串必须是 ((名 表达式)...) 形式，实际是"
            f"{to_display_string(bindings)}"
        )
    names: list[Symbol] = []
    values: list[Any] = []
    for binding in _iter_list(bindings):
        if isinstance(binding, Pair) or binding is NIL:
            parts = _list_to_python(binding, "let 的绑定")
        else:
            raise SchemeSyntaxError(
                f"let 的每个绑定必须是 (名 表达式) 形式，实际是"
                f"{to_display_string(binding)}"
            )
        if len(parts) != 2 or not isinstance(parts[0], Symbol):
            raise SchemeSyntaxError(
                f"let 的每个绑定必须是 (名 表达式) 形式，实际是"
                f"{to_display_string(binding)}"
            )
        names.append(parts[0])
        values.append(evaluate(parts[1], environment))
    return names, values
