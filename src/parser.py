"""语法分析：词（token）列表 -> 表达式（嵌套的数据结构）。

第二站。它只做"括号配对、把词组成树"这件事，不判断 ``define`` 该有几个参数，
更不碰"这个表达式怎么算"。

表达式（S-表达式）的内部表示与运行时数据**完全一致**：

- 整数/浮点/布尔/字符串 -> Python 的 ``int`` / ``float`` / ``bool`` / ``str``
- 符号                  -> :class:`src.types.Symbol`
- 列表                  -> :class:`src.types.Pair` 组成的链，末端是 ``NIL``

这一点非常关键：正因为"代码"和"数据"是同一套表示，``quote`` 才能把参数原样
交出来（spec §4.1），列表也才能和 ``cons`` 构造出的东西统一（spec §11）。
"""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from . import lexer
from .datatypes import Pair, SchemeSyntaxError, Symbol, to_scheme_list


class _Reader:
    """把词序列读成表达式。"""

    def __init__(self, tokens: Sequence[lexer.Token]) -> None:
        if not tokens or tokens[-1].kind != lexer.EOF:
            raise ValueError("词列表必须以 EOF 词结尾（请用 src.lexer.tokenize）")
        self._tokens = tokens
        self._index = 0

    # ---- 基本操作 -----------------------------------------------------

    @property
    def current(self) -> lexer.Token:
        return self._tokens[self._index]

    def advance(self) -> lexer.Token:
        token = self._tokens[self._index]
        if token.kind != lexer.EOF:
            self._index += 1
        return token

    @property
    def at_end(self) -> bool:
        return self.current.kind == lexer.EOF

    # ---- 读取一个表达式 -----------------------------------------------

    def read(self) -> Any:
        token = self.current
        if token.kind == lexer.EOF:
            raise SchemeSyntaxError(
                f"{token.line}:{token.column} 程序意外结束，还有表达式没读完"
            )
        if token.kind == lexer.LPAREN:
            return self.read_list()
        if token.kind == lexer.RPAREN:
            raise SchemeSyntaxError(f"{token.line}:{token.column} 多了一个 )")
        if token.kind == lexer.QUOTE:
            return self.read_quote()
        self.advance()
        return token.value

    def read_quote(self) -> Pair:
        """``'x`` 展开成 ``(quote x)``；``''x`` 会自然嵌套成 ``(quote (quote x))``。"""
        token = self.advance()  # 吃掉 '
        if self.at_end:
            raise SchemeSyntaxError(f"{token.line}:{token.column} ' 后面缺少数据")
        quoted = self.read()
        return to_scheme_list([Symbol("quote"), quoted])

    def read_list(self) -> Any:
        """读一个 ``( ... )``，返回 ``Pair`` 链，空表返回 ``NIL``。"""
        opening = self.advance()  # 吃掉 (
        items: list[Any] = []
        while True:
            token = self.current
            if token.kind == lexer.EOF:
                raise SchemeSyntaxError(
                    f"{opening.line}:{opening.column} 这里少了一个 )"
                )
            if token.kind == lexer.RPAREN:
                self.advance()
                return to_scheme_list(items)
            items.append(self.read())


def parse(tokens: Sequence[lexer.Token]) -> list[Any]:
    """把词列表解析成"顶层表达式"列表。"""
    reader = _Reader(tokens)
    expressions: list[Any] = []
    while not reader.at_end:
        expressions.append(reader.read())
    return expressions


def parse_all(text: str) -> list[Any]:
    """源程序文本 -> 顶层表达式列表（tokenize + parse 的便捷组合）。"""
    return parse(lexer.tokenize(text))


def parse_first(text: str) -> Any:
    """只解析第一个表达式，多余内容报错。方便测试与以后可能的 REPL。"""
    expressions = parse_all(text)
    if not expressions:
        raise SchemeSyntaxError("没有读到任何表达式")
    if len(expressions) > 1:
        raise SchemeSyntaxError("只允许一个表达式，却读到了多个")
    return expressions[0]


def iter_expressions(text: str) -> Iterator[Any]:
    """边读边产出顶层表达式，便于流式处理大文件。"""
    yield from parse_all(text)
