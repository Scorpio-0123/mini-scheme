"""词法分析：程序文本 -> 词（token）列表。

它是流水线的第一站，只认识"字符"层面的东西，完全不知道括号要配对、``define``
有几个参数——那些是 :mod:`src.parser` 的事。

规则来自 spec §3：

- ``;`` 到行尾是注释；
- 整数如 ``42`` / ``-7`` / ``0``（浮点字面量可选，这里也接受 ``1.5``）；
- ``#t`` / ``#f`` 是仅有的两种布尔写法；
- 符号如 ``foo`` / ``x1`` / ``+``；
- 字符串用双引号包住，支持 ``\\n`` ``\\t`` ``\\"`` ``\\\\`` 转义；
- ``'x`` 是 ``(quote x)`` 的简写，在词法阶段产出一个 ``QUOTE`` 词。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from .datatypes import SchemeSyntaxError, Symbol

# 词的种类。用字符串常量而不是 Enum，是为了让调试输出一眼能看懂。
LPAREN = "LPAREN"
RPAREN = "RPAREN"
QUOTE = "QUOTE"
INT = "INT"
FLOAT = "FLOAT"
BOOLEAN = "BOOLEAN"
STRING = "STRING"
SYMBOL = "SYMBOL"

#: 结束标记。解析器靠它知道"词用完了"。
EOF = "EOF"

#: 两边都能出现的单字符界符，遇到它们总是要断开当前符号。
_DELIMITERS = frozenset("()'\";")

#: 数字字面量允许出现、也允许出现在符号中间的字符。
_SYMBOL_EXTRA = frozenset("+-*/.<>=!?%&^~:@$")

_STRING_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


@dataclass(frozen=True)
class Token:
    """一个词。``line``/``column`` 用于报错时定位。"""

    kind: str
    value: Any
    line: int
    column: int

    def __str__(self) -> str:  # pragma: no cover - 仅用于调试展示
        return f"{self.kind}({self.value!r})@{self.line}:{self.column}"


class _Scanner:
    """带位置记账的单遍扫描器。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._line = 1
        self._column = 1

    # ---- 位置与取字符 -------------------------------------------------

    @property
    def at_end(self) -> bool:
        return self._pos >= len(self._text)

    def peek(self, offset: int = 0) -> str:
        index = self._pos + offset
        if index >= len(self._text):
            return ""
        return self._text[index]

    def advance(self) -> str:
        char = self._text[self._pos]
        self._pos += 1
        if char == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return char

    def skip_atmosphere(self) -> None:
        """跳过空白与注释（spec §3：``;`` 到行尾都被忽略）。"""
        while not self.at_end:
            char = self.peek()
            if char in " \t\r\n\f\v":
                self.advance()
            elif char == ";":
                while not self.at_end and self.peek() != "\n":
                    self.advance()
            else:
                return

    # ---- 各类零件 -----------------------------------------------------

    def read_string(self, line: int, column: int) -> Token:
        self.advance()  # 吃掉开引号
        chars: list[str] = []
        while True:
            if self.at_end:
                raise SchemeSyntaxError(
                    f"{line}:{column} 字符串没有闭合的双引号"
                )
            char = self.advance()
            if char == '"':
                break
            if char == "\\":
                if self.at_end:
                    raise SchemeSyntaxError(
                        f"{line}:{column} 字符串末尾的反斜杠不完整"
                    )
                escaped = self.advance()
                try:
                    chars.append(_STRING_ESCAPES[escaped])
                except KeyError:
                    raise SchemeSyntaxError(
                        f"{self._line}:{self._column - 1} 不认识的转义 \\{escaped}"
                    ) from None
            else:
                chars.append(char)
        return Token(STRING, "".join(chars), line, column)

    def read_atom(self, line: int, column: int) -> Token:
        start = self._pos
        while not self.at_end:
            char = self.peek()
            if char.isspace() or char in _DELIMITERS:
                break
            self.advance()
        raw = self._text[start : self._pos]
        return Token(_classify_atom(raw, line, column), _atom_value(raw), line, column)

    # ---- 主循环 -------------------------------------------------------

    def tokens(self) -> Iterator[Token]:
        while True:
            self.skip_atmosphere()
            if self.at_end:
                yield Token(EOF, None, self._line, self._column)
                return
            line, column = self._line, self._column
            char = self.peek()
            if char == "(":
                self.advance()
                yield Token(LPAREN, char, line, column)
            elif char == ")":
                self.advance()
                yield Token(RPAREN, char, line, column)
            elif char == "'":
                self.advance()
                yield Token(QUOTE, char, line, column)
            elif char == '"':
                yield self.read_string(line, column)
            else:
                yield self.read_atom(line, column)


def _classify_atom(raw: str, line: int, column: int) -> str:
    """决定一个原子词是整数、浮点、布尔还是符号。"""
    if raw == "#t" or raw == "#f":
        return BOOLEAN
    if _is_integer_literal(raw):
        return INT
    if _is_float_literal(raw):
        return FLOAT
    return SYMBOL


def _atom_value(raw: str) -> Any:
    """把原子词的原文转成对应的 Python 值。"""
    if raw == "#t":
        return True
    if raw == "#f":
        return False
    if _is_integer_literal(raw):
        return int(raw)
    if _is_float_literal(raw):
        return float(raw)
    return Symbol(raw)


def _is_integer_literal(raw: str) -> bool:
    body = raw[1:] if raw[:1] in "+-" else raw
    return bool(body) and body.isdigit()


def _is_float_literal(raw: str) -> bool:
    body = raw[1:] if raw[:1] in "+-" else raw
    if "." not in body:
        return False
    head, _, tail = body.partition(".")
    # 只接受 1.5 / .5 / 1. 这种形态；"." 单独出现是符号（点对语法留给以后）。
    if not head.isdigit() and head != "":
        return False
    if not tail.isdigit() and tail != "":
        return False
    return bool(head or tail)


def tokenize(text: str) -> list[Token]:
    """把源程序文本切成词列表（末尾一定有一个 ``EOF`` 词）。"""
    return list(_Scanner(text).tokens())


def describe_tokens(tokens: Iterable[Token]) -> str:
    """调试辅助：把词列表渲染成一行，便于对照词法是否正确。"""
    return " ".join(str(token) for token in tokens)
