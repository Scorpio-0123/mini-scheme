"""入口：读文件/标准输入，逐行打印结果。

CLI 约定见 spec §2：

- ``python3 src/main.py file1.scm [file2.scm ...]``
- 没有参数时从标准输入读取
- 按顺序求值每一个顶层表达式，**每个结果独占一行**；结果为 ``None``（无值，
  例如 ``display``/``newline`` 的返回值）时不打印
- 多个文件共享同一个全局环境，所以后一个文件能看见前一个文件的 ``define``

直接运行本文件（``python src/main.py``）和以模块方式运行
（``python -m src.main``）都要能用，所以下面在导入包内模块之前先把仓库根目录
放进 ``sys.path``。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

if __package__ in (None, ""):  # 以脚本方式直接运行：把仓库根目录加入搜索路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import builtins as builtins_module  # noqa: E402
from src import parser  # noqa: E402
from src import printer  # noqa: E402
from src.datatypes import SchemeError  # noqa: E402
from src.environment import Environment  # noqa: E402
from src.evaluator import evaluate  # noqa: E402

STANDARD_INPUT = "<stdin>"

USAGE = "用法：python3 src/main.py [file1.scm [file2.scm ...]]（不给文件时读标准输入）"

#: 递归深度上限（Python 帧数）。Scheme 的递归要靠 Python 的递归实现，而每层
#: Scheme 递归大约消耗 20 个 Python 帧（``evaluate`` -> ``_evaluate_form`` ->
#: 用户过程 ``apply`` -> ``evaluate_sequence`` -> ...），默认的 1000 帧连
#: ``(sum-to 100)`` 都跑不完（约需 2000 帧）。这里给到 200000 帧，实测可支持
#: 约 10000 层 Scheme 递归；再深会干净地抛 ``RecursionError``，而不是把进程
#: 撞崩（Windows 上也验证过：撞到上限时是 RecursionError，不是访问冲突）。
RECURSION_LIMIT = 200_000


def configure_recursion_limit() -> None:
    """放宽递归上限，让常见的线性/树形递归够用。只放大，不缩小。"""
    if sys.getrecursionlimit() < RECURSION_LIMIT:
        sys.setrecursionlimit(RECURSION_LIMIT)


def read_source(path: str) -> str:
    """读取一个源文件的内容（UTF-8）。"""
    return Path(path).read_text(encoding="utf-8")


def read_standard_input() -> str:
    """读取标准输入的全部内容。

    **刻意**动手按 UTF-8 解码，不走 Python 的文本流：脚本的默认 I/O 编码取自
    系统区域设置（中文 Windows 上是 GBK），而 ``.scm`` 文件是 UTF-8 的。直接用
    文本流会把源文件里的中文注释读成乱码，严重时直接抛解码错误。
    """
    stream = sys.stdin
    if hasattr(stream, "buffer"):
        return stream.buffer.read().decode("utf-8")
    return stream.read()


def run_source(text: str, environment: Environment, *, source_name: str = STANDARD_INPUT) -> int:
    """求值一段程序并逐行打印结果；返回本次运行中出错的表达式个数。"""
    try:
        expressions = parser.parse_all(text)
    except SchemeError as error:
        report(source_name, error)
        return 1
    failures = 0
    for expression in expressions:
        try:
            value = evaluate(expression, environment)
        except SchemeError as error:
            report(source_name, error)
            failures += 1
            continue
        except RecursionError:
            report(source_name, "递归太深：可能是递归缺少终止条件，或递归层数超过了上限")
            failures += 1
            continue
        if value is None:  # 无值不打印（spec §2）
            continue
        print(printer.to_write_string(value))
    return failures


def report(source_name: str, message: object) -> None:
    """把错误写到标准错误，保证标准输出只含程序结果。"""
    print(f"{source_name}: {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """程序入口：返回进程退出码。"""
    configure_recursion_limit()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(argument in ("-h", "--help") for argument in arguments):
        print(USAGE)
        return 0

    # 多个文件共享同一个全局环境（spec §2）。
    environment = builtins_module.make_global_environment()
    failures = 0

    if not arguments:
        failures += run_source(read_standard_input(), environment)
        return 0 if failures == 0 else 1

    for path in arguments:
        try:
            text = read_source(path)
        except OSError as error:
            report(path, f"无法读取文件：{error.strerror or error}")
            failures += 1
            continue
        except UnicodeDecodeError:
            report(path, "文件不是合法的 UTF-8 文本")
            failures += 1
            continue
        failures += run_source(text, environment, source_name=path)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
