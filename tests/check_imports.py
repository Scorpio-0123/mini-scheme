"""开发用自测：检查 src/ 里有没有"未导入/未定义的名字"或"没被用到的导入"。

前者会在运行时报出裸的 Python 异常（例如 ``raise SchemeNameError`` 忘了 import），
正是这一检查抓出来过一次；后者只是清理噪声。
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def collect_imports(tree: ast.AST) -> dict[str, int]:
    """名字 -> 该名字所在的行号。"""
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported[alias.asname or alias.name] = node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported[(alias.asname or alias.name).split(".")[0]] = node.lineno
    return imported


#: 模块级别的内建全局名，静态分析看不到它们的绑定。
MODULE_GLOBALS = frozenset({"__file__", "__name__", "__doc__", "__package__", "__spec__"})


def collect_defined_and_stored(tree: ast.AST) -> set[str]:
    names: set[str] = set(MODULE_GLOBALS)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)  # except X as error
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def check_module(path: Path) -> list[str]:
    problems: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = collect_imports(tree)
    available = collect_defined_and_stored(tree)

    used: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.setdefault(node.id, node.lineno)
        elif isinstance(node, ast.Attribute):
            # 处理 `from . import parser` 之后用 `parser.parse_all(...)` 的情况
            if isinstance(node.value, ast.Name):
                used.setdefault(node.value.id, node.lineno)

    for name, lineno in sorted(used.items()):
        if name in available or hasattr(builtins, name):
            continue
        problems.append(f"{path.name}:{lineno}: 使用了未定义/未导入的名字 {name!r}")

    for name, lineno in sorted(imported.items()):
        if name not in used and name not in {"annotations"}:
            problems.append(f"{path.name}:{lineno}: 导入了但没用到的名字 {name!r}")

    return problems


def main() -> int:
    all_problems: list[str] = []
    files = sorted(SRC.glob("*.py"))
    for path in files:
        all_problems.extend(check_module(path))
    for problem in all_problems:
        print(problem)
    print(f"\n检查了 {len(files)} 个模块，{'发现 ' + str(len(all_problems)) + ' 个问题' if all_problems else '没有问题'}")
    return 1 if all_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
