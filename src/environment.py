"""环境：变量绑定表 + 指向外层环境的指针。

这是实现**词法作用域**的关键数据结构（spec §9）。一个 :class:`Environment`
就是一层"名字 -> 值"的表，外加一个指向外层的 ``parent``：

- 查值：先看本层，没有就顺着 ``parent`` 一直往外找；
- 绑定：默认绑在**最内层**（``define`` 的语义），也可以指定某一层；
- ``lambda`` 求值时捕获当时的环境，调用时以它为 ``parent`` 新建一层——
  于是函数体里看到的永远是"定义时"的变量，而不是"调用时"的。

多个源文件共享同一个全局环境（spec §2），这是靠入口只创建一个全局环境实现的。
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Optional

from .printer import describe_type
from .datatypes import (
    SchemeArityError,
    SchemeNameError,
    SchemeTypeError,
    Symbol,
)


class BuiltinProcedure:
    """一个内置过程，例如 ``+``、``car``、``not``。

    内置过程也是普通的"值"：可以被绑定到名字、传给别的函数、被谓词
    ``procedure?`` 识别（spec §5）。``arity`` 形如 ``(最少个数, 最多个数)``，
    ``最多个数`` 为 ``None`` 表示可变参数（如 ``+``）。
    """

    __slots__ = ("name", "function", "min_args", "max_args")

    def __init__(
        self,
        name: str,
        function: Callable[..., Any],
        min_args: int = 0,
        max_args: Optional[int] = None,
    ) -> None:
        self.name = name
        self.function = function
        self.min_args = min_args
        self.max_args = max_args

    def check_arity(self, count: int) -> None:
        """实参个数不对时抛出 :class:`SchemeArityError`。"""
        if count < self.min_args:
            raise SchemeArityError(
                f"{self.name} 至少需要 {self.min_args} 个参数，实际给了 {count} 个"
            )
        if self.max_args is not None and count > self.max_args:
            raise SchemeArityError(
                f"{self.name} 最多接受 {self.max_args} 个参数，实际给了 {count} 个"
            )

    def apply(self, args: list[Any]) -> Any:
        """``args`` 已经由求值器求值完毕（spec §5：内置过程先全部求值再调用）。"""
        self.check_arity(len(args))
        return self.function(*args)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"#<builtin {self.name}>"


class Environment:
    """一层作用域。``parent`` 为 ``None`` 表示这是全局环境。"""

    __slots__ = ("_bindings", "parent")

    def __init__(self, parent: Optional["Environment"] = None) -> None:
        self._bindings: dict[Symbol, Any] = {}
        self.parent = parent

    # ---- 读取 ---------------------------------------------------------

    def lookup(self, name: Any) -> Any:
        """查找名字对应的值，找不到就抛 :class:`SchemeNameError`。"""
        environment: Optional[Environment] = self
        while environment is not None:
            if name in environment._bindings:
                return environment._bindings[name]
            environment = environment.parent
        raise SchemeNameError(f"未定义的名字：{name}")

    def find(self, name: Any) -> Optional["Environment"]:
        """返回定义了 ``name`` 的那一层环境，找不到返回 ``None``。"""
        environment: Optional[Environment] = self
        while environment is not None:
            if name in environment._bindings:
                return environment
            environment = environment.parent
        return None

    def contains(self, name: Any) -> bool:
        """``name`` 在可见范围内是否已绑定。"""
        return self.find(name) is not None

    # ---- 写入 ---------------------------------------------------------

    def define(self, name: Any, value: Any) -> None:
        """在**本层**新增/覆盖绑定（``define`` 的语义：绑在当前环境）。"""
        self._bindings[name] = value

    def define_all(self, names: Any, values: Any) -> None:
        """一次性把若干名字绑到若干值上，用于调用用户函数时建立参数层。"""
        names = list(names)
        values = list(values)
        if len(names) != len(values):
            raise SchemeArityError(
                f"参数个数不匹配：需要 {len(names)} 个，实际给了 {len(values)} 个"
            )
        for name, value in zip(names, values):
            self.define(name, value)

    # ---- 派生 ---------------------------------------------------------

    def child(self) -> "Environment":
        """新建一层以 ``self`` 为外层的环境（``let``、函数调用都用它）。"""
        return Environment(parent=self)

    def names(self) -> Iterator[Symbol]:
        """产出可见范围内所有名字，先本层后外层。"""
        environment: Optional[Environment] = self
        while environment is not None:
            yield from environment._bindings
            environment = environment.parent

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"<Environment {len(self._bindings)} bindings>"


def bind_builtins(environment: Environment, procedures: dict[str, Any]) -> None:
    """把一批内置过程装进环境（spec §5 的"内置库放进初始环境"）。"""
    for name, procedure in procedures.items():
        if not isinstance(procedure, BuiltinProcedure):
            raise SchemeTypeError(
                f"内置过程 {name} 的类型不对：{describe_type(procedure)}"
            )
        environment.define(Symbol(name), procedure)
