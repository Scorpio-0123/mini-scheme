"""独立复核：解开 autograder 内置用例，自己跑一遍并逐字节比对。

目的不是替代评分器，而是**独立验证评分器的结论**——直接读它内部的
(程序, 期望输出)，用与评分器相同的方式（独立进程、stdin 喂程序、逐字节比对
stdout）再算一遍，看两边是否一致。
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 从临时目录 import _cases 时不要留下 __pycache__，否则清理会撞上 Windows 的
# "目录非空/权限"问题。
sys.dont_write_bytecode = True


def load_cases() -> dict[str, tuple[str, str]]:
    """从 pyz 里读出 {用例名: (程序, 期望输出)}。

    走 import 而不是自己解 base64，避免我抄错；pyz 解到临时目录后立刻清理。
    """
    scratch = REPO / "tests" / "tmp" / "verify_ag"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(REPO / "autograder.pyz") as archive:
            archive.extract("_cases.py", scratch)
        sys.path.insert(0, str(scratch))
        import _cases  # type: ignore[import-not-found]

        return {
            name: tuple(base64.b64decode(part).decode("utf-8") for part in pair)
            for name, pair in _cases.CASES.items()
        }
    finally:
        sys.path.remove(str(scratch))
        sys.modules.pop("_cases", None)
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    cases = load_cases()
    print(f"从 autograder.pyz 读到 {len(cases)} 组用例\n")

    failures = 0
    for name in sorted(cases):
        program, expected = cases[name]
        # 与评分器一致：独立进程、stdin 喂程序、用默认编码读取输出
        completed = subprocess.run(
            [sys.executable, str(REPO / "src" / "main.py")],
            input=program,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=REPO,
            timeout=60,
        )
        ok = completed.returncode == 0 and completed.stdout == expected
        if ok:
            print(f"  一致   {name}")
            continue

        failures += 1
        print(f"  不一致 {name}")
        if completed.returncode != 0:
            print(f"         退出码 {completed.returncode}，stderr：")
            for line in completed.stderr.strip().splitlines():
                print(f"           {line}")
        actual_lines = completed.stdout.splitlines()
        expected_lines = expected.splitlines()
        for index in range(max(len(actual_lines), len(expected_lines))):
            got = actual_lines[index] if index < len(actual_lines) else "<缺行>"
            want = expected_lines[index] if index < len(expected_lines) else "<无此期望行>"
            if got != want:
                print(f"         第 {index + 1} 行：期望 {want!r}，实际 {got!r}")

    print()
    if failures:
        print(f"{len(cases) - failures}/{len(cases)} 组一致，{failures} 组不符")
        return 1
    print(f"全部 {len(cases)} 组自算结果与评分器一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
