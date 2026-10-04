"""用 Python 自身（而不是 PowerShell 的 Get-Content）数行数，并核对 README。

PowerShell 的 Get-Content 在中文 Windows 上按 GBK 解码 UTF-8 文件，会把内容读坏、
少算行数，所以行数必须以 Python 为准。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def line_counts() -> dict[str, int]:
    return {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in sorted((REPO / "src").glob("*.py"))
    }


def readme_claims() -> dict[str, int]:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    claimed: dict[str, int] = {}
    for match in re.finditer(r"\[(\w+\.py)\]\(src/\1\) \| (\d+) \|", readme):
        claimed[match.group(1)] = int(match.group(2))
    total = re.search(r"\*\*([\d,]+)\*\* \| 含注释", readme)
    if total:
        claimed["合计"] = int(total.group(1).replace(",", ""))
    return claimed


def run_stdin(program: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(REPO / "src" / "main.py")],
        input=program,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO,
    )
    return completed.stdout.rstrip("\n")


def main() -> int:
    problems: list[str] = []
    actual = line_counts()
    claimed = readme_claims()

    print("模块行数（Python 计数）：")
    for name, count in actual.items():
        if name == "__init__.py":
            continue
        want = claimed.get(name)
        if want != count:
            problems.append(f"{name}: 实际 {count} 行，README 写 {want}")
        print(f"  {name:<18} {count:>4}   README 写 {want}")

    real_total = sum(v for k, v in actual.items() if k != "__init__.py")
    print(f"  {'合计':<17} {real_total:>4}   README 写 {claimed.get('合计')}")
    if real_total != claimed.get("合计"):
        problems.append(f"合计: 实际 {real_total}，README 写 {claimed.get('合计')}")

    print("\nREADME 行为示例（注意 define 的结果也会打印）：")
    checks = [
        (
            "(map ...) 例子",
            "(define (map f xs)\n  (if (null? xs) '() (cons (f (car xs)) (map f (cdr xs)))))\n"
            "(map (lambda (x) (* x x)) '(1 2 3 4))",
            "map\n(1 4 9 16)",
        ),
        ("(/ -7 2) 向零截断", "(/ -7 2)", "-3"),
        ("(quotient -7 2)", "(quotient -7 2)", "-3"),
        ("(< 2 3 4) 链式比较", "(< 2 3 4)", "#t"),
        ("(eq? '() '())", "(eq? '() '())", "#t"),
        ("(eq? 1 #t) 类型区分", "(eq? 1 #t)", "#f"),
        (
            "(sum-to 100) 深递归",
            "(define (sum-to n) (if (= n 0) 0 (+ n (sum-to (- n 1)))))\n(sum-to 100)",
            "sum-to\n5050",
        ),
        ('display 不带引号', '(display "hi")', "hi"),
        ("字符串带引号转义", '"a\\nb"', '"a\\nb"'),
    ]
    for label, program, want in checks:
        got = run_stdin(program)
        ok = got == want
        if not ok:
            problems.append(f"{label}: 期望 {want!r}，实际 {got!r}")
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<22} -> {got!r}")

    print()
    if problems:
        for problem in problems:
            print("问题:", problem)
        return 1
    print("README 的数字与示例全部与代码一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
