"""开发用自测：核对 example 里每行注释标注的期望输出。

用法：

- ``python tests/check_examples.py`` —— 逐个检查 ``example/`` 下所有文件
- ``python tests/check_examples.py example/01_arithmetic.scm`` —— 只检查指定文件

期望值取自每行结尾的 ``; → 值`` 注释。有些示例把 ``display``/``newline`` 的
副作用写在前面、期望注释只标后面几行，所以这里核对的是"**期望值按顺序出现在
程序输出的第几行**"，而不是逐行一一对应。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 匹配行尾注释里的 "→ 期望值"，期望值到分号为止。
ARROW = re.compile(r";\s*→\s*([^;]+)")
# 值后面直接跟说明文字（没有再用分号隔开）的情况，例如 '"a\nb"    换行按 \n 转义打印'。
ANNOTATION = re.compile(r"\s{2,}\S.*$")


def expected_values(path: Path) -> list[str]:
    """取出一个 .scm 文件里所有 ``; → 值`` 注释标注的期望输出。"""
    wanted: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ARROW.search(line)
        if not match:
            continue
        text = match.group(1).strip()
        stripped = ANNOTATION.sub("", text).strip()
        wanted.append(stripped or text)
    return wanted


def run_interpreter(path: Path) -> tuple[int, list[str], str]:
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, str(REPO / "src" / "main.py"), str(path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        cwd=REPO,
    )
    return completed.returncode, completed.stdout.splitlines(), completed.stderr


def check(path: Path, *, show_stderr: bool = False) -> tuple[bool, int, int]:
    """返回 (是否全部对得上, 对上的条数, 总条数)。"""
    path = path if path.is_absolute() else (REPO / path)
    try:
        label = path.relative_to(REPO)
    except ValueError:
        label = path
    print(f"--- {label} ---")

    wanted = expected_values(path)
    if not wanted:
        print("  （文件里没有 '; → 值' 形式的期望注释，跳过）")
        return True, 0, 0

    code, actual, stderr = run_interpreter(path)
    if show_stderr and stderr.strip():
        print("  stderr:")
        for line in stderr.strip().splitlines()[:4]:
            print(f"    {line}")
        if len(stderr.strip().splitlines()) > 4:
            print(f"    ...（共 {len(stderr.strip().splitlines())} 行）")

    # 在 actual 里按顺序找 wanted 的每一项（子序列匹配）。
    matched = 0
    cursor = 0
    failures: list[str] = []
    for index, want in enumerate(wanted):
        found = None
        for position in range(cursor, len(actual)):
            if actual[position] == want:
                found = position
                break
        if found is None:
            failures.append(f"  第 {index + 1:2d} 条: 输出里找不到 {want!r}")
        else:
            matched += 1
            cursor = found + 1

    for line in failures:
        print(line)
    if len(actual) < len(wanted):
        print(f"  提示：期望至少 {len(wanted)} 行输出，实际只有 {len(actual)} 行")

    if matched == len(wanted):
        print(f"  {matched}/{len(wanted)} 条通过（共 {len(actual)} 行输出）")
        return True, matched, len(wanted)

    print(f"  实际输出：{actual}")
    if code == 0:
        print(f"  （注：退出码为 0，说明不是报错，而是输出内容/顺序对不上）")
    return False, matched, len(wanted)


def main(argv: list[str]) -> int:
    paths = [Path(argument) for argument in argv] if argv else sorted((REPO / "example").glob("*.scm"))
    if not paths:
        print("没有找到要检查的文件")
        return 1
    results = [check(path, show_stderr=True) for path in paths]
    ok_files = sum(1 for ok, _, _ in results if ok)
    matched = sum(m for _, m, _ in results)
    total = sum(t for _, _, t in results)
    print(f"\n{ok_files}/{len(results)} 个文件对得上；{matched}/{total} 条期望值命中")
    return 0 if ok_files == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
