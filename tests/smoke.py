"""冒烟自测：把所有出错路径和 CLI 约定都走一遍。

关注两件事：

1. 出错时抛出的必须是 :class:`SchemeError` 的子类（而不是裸的 Python 异常），
   否则入口就没法给出干净的错误信息；
2. 入口的 CLI 约定（spec §2）：每个结果一行、``None`` 不打印、多文件共享环境、
   没有参数时读标准输入。
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

# 控制台可能是 GBK，让自测脚本自己的中文输出不要炸掉。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import parser  # noqa: E402
from src import printer  # noqa: E402
from src.builtins import make_global_environment  # noqa: E402
from src.datatypes import SchemeError  # noqa: E402
from src.evaluator import evaluate  # noqa: E402

# 每一行都应该以 SchemeError 的子类报错收场。
ERROR_INPUTS = [
    # 词法/语法
    "(1 2",
    "1 2)",
    ")",
    "'",
    '"abc',
    '"bad \\q escape"',
    # 语序错误（spec §11 第一条）
    "(1 + 2)",
    "(1 2 3)",
    # 类型错误
    "(+ 1 #t)",
    "(+ 1 'a)",
    "(- 1 \"s\")",
    "(car 5)",
    "(cdr 5)",
    "(length (cons 1 2))",
    "(abs 'x)",
    # 未定义的名字
    "foo",
    "(foo 1)",
    "undefined-proc",
    # 参数个数
    "(-)",
    "(/)",
    "(abs)",
    "(abs 1 2)",
    "(not)",
    "(modulo 1)",
    "(car)",
    "(car '(1) '(2))",
    "(eq? 1)",
    "(display)",
    "(newline 1)",
    "(zero?)",
    "(even? 1 2)",
    "(< 1)",
    "(if)",
    "(if #t)",
    "(if #t 1 2 3)",
    "(cond ())",
    "(cond 5)",
    "(if #t (else 1))",
    # define / lambda / let 的语法检查
    "(define)",
    "(define x)",
    "(define x 1 2)",
    "(define 1 2)",           # 第一个参数既不是符号也不是 (名 参数...) 形式
    "(define (f 1) 2)",       # 参数名必须是符号
    "(define (f))",           # 函数体不能为空
    "(lambda)",
    "(lambda (x))",           # 函数体不能为空
    "(lambda x 1)",           # 参数表必须是列表
    "(lambda (1) 2)",         # 参数名必须是符号
    "(let)",
    "(let x 1)",              # 绑定串必须是 ((名 表达式)...) 形式
    "(let ((x)) x)",          # 每个绑定必须是 (名 表达式)
    "(let ((x 1 2)) x)",
    "(let ((1 2)) 1)",        # 绑定名必须是符号
    # 除零（modulo 向零截断，所以 -7 除以 2 是 -1 而不是 1）
    "(modulo 1 0)",
    "(quotient 1 0)",
    "(/ 1 0)",
]

# (源码, 期望打印文本)；None 表示"无值、不该打印"。
VALUE_CASES = [
    # append 的最后一个参数可以是任意值（spec §5 只要求"拼接若干列表"）
    ("(append '(1 2) 3)", "(1 2 . 3)"),
    ("(append '(1 2) '(3 4))", "(1 2 3 4)"),
    # cond 全部不匹配 / 空 cond / 空 else 子句 -> 无值（spec §4.3）
    ("(cond)", None),
    ("(cond (else))", None),
    ("(cond ((= 1 2) 'a))", None),
    ("(cond ((= 1 2) 'a) (else))", None),
    # 子句里没有表达式时返回测试值本身
    ("(cond (42))", "42"),
    ("(cond (#f) (else 7))", "7"),
    # 列表/点对的打印（spec §6、§8）
    ("(cons 1 2)", "(1 . 2)"),
    ("(list 1 2 3)", "(1 2 3)"),
    ("(length '(a b c d))", "4"),
    ("(car '(1 2 3))", "1"),
    ("(cdr '(1 2 3))", "(2 3)"),
    ("(null? '())", "#t"),
    ("(pair? '(1 2))", "#t"),
    ("(pair? '())", "#f"),
    ("(list? '(1 2))", "#t"),
    ("(list? (cons 1 2))", "#f"),
    # 谓词
    ("(number? 5)", "#t"),
    ("(number? 'x)", "#f"),
    ("(boolean? #t)", "#t"),
    ("(symbol? 'x)", "#t"),
    ("(string? \"s\")", "#t"),
    ("(procedure? car)", "#t"),
    ("(procedure? 1)", "#f"),
    ("(even? 8)", "#t"),
    ("(odd? 7)", "#t"),
    ("(zero? 0)", "#t"),
    # eq? / equal?（spec §11 的三个易错点）
    ("(eq? '() '())", "#t"),
    ("(eq? '(1) '(1))", "#f"),
    ("(equal? '(1 2 3) (list 1 2 3))", "#t"),
    ("(equal? #t 1)", "#f"),
    ("(equal? 'a \"a\")", "#f"),
    # display 的结果是 None
    ("(display \"a\")", None),
    ("(newline)", None),
]

# 整段程序用例：(程序, 期望的逐行输出, 是否期望以非 0 退出)。
# 整段程序共享一个全局环境，可用来验证 define/闭包/递归。
# 期望报错的用例要注意：报错之前的表达式**仍然会打印**（它们是独立求值的）。
PROGRAM_CASES: list[tuple[str, str, bool]] = [
    # define 返回被定义的符号名（spec §4.5；顶层会打印）
    ("(define pi 3)", "pi", False),
    ("(define pi 3)\n(+ pi 1)", "pi\n4", False),
    # lambda 求值不求值函数体，被调用时才求值（spec §4.6）
    ("((lambda (x) (* x 2)) 5)", "10", False),
    ("(define square (lambda (x) (* x x)))\n(square 7)", "square\n49", False),
    # define 的函数简写，等价于 (define f (lambda ...))（spec §4.5）
    ("(define (cube x) (* x x x))\n(cube 3)", "cube\n27", False),
    # let：并行绑定 + begin 语义（spec §4.7）
    ("(let ((x 3) (y 4)) (+ x y))", "7", False),
    ("(let ((a 1)) (let ((b (+ a 1))) (* a b)))", "2", False),
    ("(let () 42)", "42", False),
    ("(let ((x 1)) (define y 2) (+ x y))", "3", False),  # 函数体按 begin 语义
    # 并行绑定：第二个绑定看不见第一个（z 故意没有预定义）
    ("(let ((z 2) (w z)) w)", "", True),
    # let 引入的名字只在自己体内可见：离开 let 就查不到了
    ("(let ((only 1)) only)\nonly", "1", True),
    # 把非过程当函数调用（spec §11 第一条的报错场景）；define 本身成功所以先打印 f
    ("(define (f x) (x))\n(f 5)", "f", True),
    ("(let ((g 1)) (g))", "", True),
    # 重名绑定后一个生效（autograder 010 的用例）
    ("(let ((x 1) (x 2)) x)", "2", False),
    # 闭包：捕获定义时的环境（spec §4.6/§9）
    (
        "(define (make-adder n) (lambda (x) (+ x n)))\n"
        "(define add5 (make-adder 5))\n"
        "(add5 10)\n"
        "((make-adder 100) 7)",
        "make-adder\nadd5\n15\n107",
        False,
    ),
    # 递归：define 的函数体内能看见自己的名字（spec §7）
    (
        "(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))\n(fact 10)",
        "fact\n3628800",
        False,
    ),
    (
        "(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))\n(fib 15)",
        "fib\n610",
        False,
    ),
    # 用语言本身定义 map（函数体内递归 + 闭包；spec §7 提到 009 就是这么写的）
    (
        "(define (map f xs)\n"
        "  (if (null? xs) '() (cons (f (car xs)) (map f (cdr xs)))))\n"
        "(map (lambda (x) (* x x)) '(1 2 3 4))",
        "map\n(1 4 9 16)",
        False,
    ),
]


def check_value_cases() -> int:
    """核对一批应该求值成功的用例（含内置列表/谓词过程）。"""
    failures = 0
    for source, want in VALUE_CASES:
        environment = make_global_environment()
        try:
            expression = parser.parse_first(source)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                value = evaluate(expression, environment)
        except SchemeError as error:
            print(f"FAIL {source:<34} -> 不该报错：{type(error).__name__}: {error}")
            failures += 1
            continue
        printed = buffer.getvalue()
        if value is None:
            # None 不打印；display/newline 的副作用输出要单独核对
            expected_output = ""
            if source == '(display "a")':
                expected_output = "a"
            elif source == "(newline)":
                expected_output = "\n"
            if printed != expected_output:
                print(f"FAIL {source:<34} -> 副作用输出 {printed!r}，期望 {expected_output!r}")
                failures += 1
            elif want is not None:
                print(f"FAIL {source:<34} -> 期望 {want!r}，实际无值")
                failures += 1
            else:
                print(f"ok   {source:<34} -> (无值，不打印)")
            continue
        got = printer.to_write_string(value)
        if got != want:
            print(f"FAIL {source:<34} -> 期望 {want!r} 实际 {got!r}")
            failures += 1
        else:
            print(f"ok   {source:<34} -> {got}")
    return failures


def check_program_cases() -> int:
    """把整段程序喂给 src/main.py，核对逐行输出（覆盖 define/lambda/let/递归/闭包）。"""
    failures = 0
    # 用仓库内的临时目录而不是系统临时目录：工作区之外可能被沙箱挡住。
    directory = REPO / "tests" / "tmp" / "programs"
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for index, (program, want, expect_error) in enumerate(PROGRAM_CASES, start=1):
            path = directory / f"case{index}.scm"
            path.write_text(program + "\n", encoding="utf-8")
            result = run_cli([str(path)])
            expected_output = want + "\n" if want else ""
            if result.stdout != expected_output:
                print(
                    f"FAIL {_first_line(program):<46}\n"
                    f"     期望输出 {expected_output!r}\n"
                    f"     实际输出 {result.stdout!r}\n"
                    f"     stderr {result.stderr.strip()!r}"
                )
                failures += 1
                continue
            if expect_error and result.returncode == 0:
                print(f"FAIL {_first_line(program):<46} -> 期望非 0 退出码，实际成功")
                failures += 1
                continue
            if not expect_error and result.returncode != 0:
                print(
                    f"FAIL {_first_line(program):<46} -> 意外失败（退出码 "
                    f"{result.returncode}）：{result.stderr.strip()!r}"
                )
                failures += 1
                continue
            label = "如期报错" if expect_error else repr(want)
            print(f"ok   {_first_line(program):<46} -> {label}")
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    return failures


def _first_line(program: str) -> str:
    line = program.strip().splitlines()[0]
    return line if len(line) <= 44 else line[:41] + "..."


def check_error_paths() -> int:
    failures = 0
    for source in ERROR_INPUTS:
        environment = make_global_environment()
        try:
            expressions = parser.parse_all(source)
            for expression in expressions:
                evaluate(expression, environment)
        except SchemeError as error:
            print(f"ok   {source:<24} -> {type(error).__name__}")
        except Exception as error:  # noqa: BLE001 - 这里就是要抓"不该出现"的异常
            print(f"FAIL {source:<24} -> 非 SchemeError: {type(error).__name__}: {error}")
            failures += 1
        else:
            print(f"FAIL {source:<24} -> 期望报错，却求值成功")
            failures += 1
    return failures


def run_cli(arguments: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    # 强制子进程用 UTF-8 写输出，否则在中文 Windows 上它会按 GBK 写，
    # 自测脚本就会把错误信息读成乱码、比对失败。
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, str(REPO / "src" / "main.py"), *arguments],
        input=stdin_text,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        cwd=REPO,
    )
    return completed


def check_cli() -> int:
    failures = 0
    scratch = REPO / "tests" / "tmp"
    scratch.mkdir(exist_ok=True)

    def expect(label: str, got: str, want: str) -> None:
        nonlocal failures
        if got == want:
            print(f"ok   {label}")
        else:
            print(f"FAIL {label}\n     期望 {want!r}\n     实际 {got!r}")
            failures += 1

    # 1. 单个文件：每个结果一行
    result = run_cli(["example/01_arithmetic.scm"])
    expect(
        "单文件逐行输出 + 退出码 0",
        result.stdout,
        "3\n5\n12\n3\n2\n3\n1024\n4\n#t\n#t\n#f\n#f\n#t\n#t\n",
    )
    if result.returncode != 0:
        print(f"FAIL 单文件退出码 = {result.returncode}")
        failures += 1

    # 2. 标准输入
    result = run_cli([], "(+ 1 2)\n(* 3 4)\n")
    expect("无参数读标准输入", result.stdout, "3\n12\n")

    # 3. 多个文件按顺序处理，各文件的输出按顺序拼接
    first = scratch / "a.scm"
    second = scratch / "b.scm"
    first.write_text("(+ 1 2)\n(* 3 4)\n", encoding="utf-8")
    second.write_text("(- 10 4 1)\n", encoding="utf-8")
    result = run_cli([str(first), str(second)])
    expect("多文件按顺序求值", result.stdout, "3\n12\n5\n")

    # 4. display / newline 的返回值是 None，不该多打印行（spec §2）
    third = scratch / "c.scm"
    third.write_text('(display "hi")\n(newline)\n(+ 1 1)\n', encoding="utf-8")
    result = run_cli([str(third)])
    expect("display/newline 不额外打印", result.stdout, "hi\n2\n")

    # 5. 出错时报到 stderr，标准输出仍然是干净的结果
    fourth = scratch / "d.scm"
    fourth.write_text("(+ 1 2)\n(foo)\n(+ 3 4)\n", encoding="utf-8")
    result = run_cli([str(fourth)])
    expect("出错行跳过、stdout 只留结果", result.stdout, "3\n7\n")
    if "未定义的名字" in result.stderr and result.returncode != 0:
        print("ok   出错信息走 stderr 且退出码非 0")
    else:
        print(f"FAIL stderr/退出码不符合预期: {result.stderr!r} code={result.returncode}")
        failures += 1

    # 6. 文件不存在
    result = run_cli(["no-such-file.scm"])
    if result.returncode != 0 and "无法读取文件" in result.stderr:
        print("ok   文件不存在时报错")
    else:
        print(f"FAIL 文件不存在时行为不符合预期: {result.stderr!r}")
        failures += 1

    # 7. --help
    result = run_cli(["--help"])
    if result.returncode == 0 and "用法" in result.stdout:
        print("ok   --help")
    else:
        print("FAIL --help")
        failures += 1

    return failures


def main() -> int:
    print("=== 期望求值成功的用例 ===")
    failures = check_value_cases()
    print("\n=== 整段程序（define/lambda/let/递归/闭包）===")
    failures += check_program_cases()
    print("\n=== 出错路径 ===")
    failures += check_error_paths()
    print("\n=== CLI 约定 ===")
    failures += check_cli()
    print()
    print(f"{failures} 处不符" if failures else "全部通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
