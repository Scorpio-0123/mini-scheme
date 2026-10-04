"""mini-Scheme 解释器。

模块划分（对应 README §4 建议的流水线）：

| 模块 | 职责 |
|---|---|
| :mod:`src.lexer` | 词法：程序文本 -> 词（token）列表 |
| :mod:`src.parser` | 语法：词 -> 表达式（嵌套的数据结构） |
| :mod:`src.environment` | 环境：变量绑定表 + 指向外层环境的指针 |
| :mod:`src.printer` | 打印：值 -> 文本 |
| :mod:`src.builtins` | 内置库：spec §5 的全部内置过程，装进初始环境 |
| :mod:`src.evaluator` | 求值器：表达式 -> 值（心脏） |
| :mod:`src.datatypes` | 数据模型：符号、点对、空表、错误类型 |
| :mod:`src.main` | 入口：读文件/标准输入，逐行打印结果 |

用法：``python3 src/main.py example/01_arithmetic.scm``
"""

__all__ = [
    "builtins",
    "datatypes",
    "environment",
    "evaluator",
    "lexer",
    "main",
    "parser",
    "printer",
]
