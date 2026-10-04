# mini-Scheme 解释器

从零手写的 mini-Scheme 解释器（Python 3，无第三方依赖）。按流水线拆成职责单一的小模块，实现 [spec.md](spec.md) 规定的完整语言子集：前缀表达式、特殊形式、25+ 个内置过程、点对列表、闭包与递归。

**验收状态**：仓库自带评分器 `autograder.pyz` **12 / 12 全部通过**（含由第三方脚本独立复核，见 [验证](#验证)）。

```console
$ python3 autograder.pyz python3 src/main.py
  PASS  001_arithmetic
  PASS  002_comparisons
  ...
  PASS  012_predicates

12 passed, 0 failed
```

## 快速开始

需要 Python 3.10+（开发环境为 3.14）。无需安装任何依赖。

```bash
# 跑一个示例：每行注释都标注了期望输出
python3 src/main.py example/03_functions.scm

# 读标准输入（不给文件参数时）
echo '(+ 1 2)' | python3 src/main.py

# 跑官方评分器
python3 autograder.pyz python3 src/main.py

# 只跑某一组
python3 autograder.pyz python3 src/main.py --case=009
```

## 架构

解释器就是一条流水线：**程序文本 ──读──→ 表达式 ──算──→ 值 ──打印──→ 结果**。每个模块只负责其中一段：

```
src/
├── main.py         入口：读文件/stdin，逐行打印结果，错误处理与退出码
├── lexer.py        词法：文本 → 词（token）
├── parser.py       语法：词 → 表达式（Pair 链）
├── evaluator.py    求值器：表达式 → 值（evaluate ↔ apply 互递归）
├── environment.py  环境：绑定表 + 外层指针、内置过程包装
├── builtins.py     内置库：spec §5 的全部过程 + 初始环境
├── printer.py      打印：值 → 文本（write / display 两种模式）
└── datatypes.py    数据模型：Symbol、Pair、NIL、错误类型
```

| 模块 | 行数 | 职责 |
|---|---:|---|
| [lexer.py](src/lexer.py) | 220 | 注释、字符串转义、`'` 简写、带行列号的报错 |
| [parser.py](src/parser.py) | 116 | 括号配对，`'x` 展开为 `(quote x)` |
| [evaluator.py](src/evaluator.py) | 417 | 9 个特殊形式、闭包、递归 |
| [builtins.py](src/builtins.py) | 463 | 算术 / 比较 / 布尔 / 列表 / 谓词 / 输出 |
| [datatypes.py](src/datatypes.py) | 185 | `Symbol`、`Pair`、`NIL` 单例、错误层级 |
| [environment.py](src/environment.py) | 143 | 词法作用域链、参数绑定、arity 检查 |
| [printer.py](src/printer.py) | 120 | 真列表/点对打印、字符串转义 |
| [main.py](src/main.py) | 132 | CLI 约定、递归上限 |
| **合计** | **1796** | 含注释与文档字符串 |

### 求值器的核心

两个**互相递归**的函数（[evaluator.py](src/evaluator.py)）：

- `evaluate(expr, env)`：符号 → 查环境；字面量 → 原样返回；括号表达式 → 特殊形式走各自规则，否则先求值操作符与全部实参，再交给 `apply_procedure`
- `apply_procedure(proc, args)`：内置过程直接调用；用户闭包新建一层环境绑定形参（外层指向**定义时**环境），再回到 `evaluate` 求值函数体

### 关键设计决策

**代码即数据，用同一套表示。** 表达式和运行时数据都是 `Pair` 链 + `Symbol` + `NIL`，所以 `quote` 只需原样返回参数，`'(1 2 3)` 与 `(cons 1 '(2 3))` 天然一致。这是 spec §11 里"列表打印成 `(1 2 . 3)` 或卡死"那条坑的根因。

**`NIL` 是单例，且不等于 `None`。** `None` 被用来表示"无值"（`display`/`newline` 的返回值，顶层不打印）；空表另有单例，才能满足 `(eq? '() '())` → `#t`。

**类型判断先于值判断。** 因为 Python 里 `True == 1`、`Symbol` 是 `str` 的子类，`eq?`/`equal?`/`number?` 一律先比类型族再比值，避免 spec §11 点名的两个误判。整数除法按语言要求向零截断（`(/ -7 2)` → `-3`），不能用 Python 的 `//`（会得 `-4`）。

**`define` 的函数简写复用 `lambda`。** `(define (f x) 体)` 直接构造带名字的 `UserProcedure`，所以错误信息是 `f 需要 1 个参数`，而不是笼统的 `lambda`。函数体内能看见自己的名字，递归无需额外语法。

**`let` 严格并行绑定。** 先在**外层**环境把所有绑定表达式求完，再一次性装进新环境。串行绑定是 spec §11 点名的常见错法，所以代码刻意分成两段。

**递归上限。** 每层 Scheme 递归约消耗 20 个 Python 帧，默认 1000 帧连 `(sum-to 100)`（约需 2000 帧）都跑不完。实测确认在 Windows 上撞到上限时是干净的 `RecursionError` 而非进程崩溃，因此把上限设为 20 万帧（约支持 1 万层 Scheme 递归）。

## 验证

四层验证，全部可复现：

| 手段 | 命令 | 结果 |
|---|---|---|
| 官方评分器 | `python3 autograder.pyz python3 src/main.py` | **12 passed, 0 failed** |
| 独立复核评分器结论 | `python3 tests/verify_autograder.py` | 12 组逐字节一致 |
| 示例程序逐行核对 | `python3 tests/check_examples.py` | 6 文件、**46/46** 条注释期望值命中 |
| 边界与出错路径 | `python3 tests/smoke.py` | **117** 项通过（35 求值 + 18 整段程序 + 56 出错 + 8 CLI） |
| 静态检查 | `python3 tests/check_imports.py` | 9 模块无"未定义/未使用"导入 |

`tests/verify_autograder.py` 的作用是不轻信评分器的 self-report：它从 `autograder.pyz` 内部读出 `(程序, 期望输出)`，用与评分器相同的方式（独立进程、stdin 喂程序、逐字节比对 stdout）重算一遍。负向对照也验证过——把 `src/main.py` 换成只 `print("42")` 的桩，评分器会正确报 `FAIL`，说明 PASS 不是恒真。

## 支持的语法

**特殊形式**（spec §4）：`quote` / `if` / `cond` / `and` / `or` / `define` / `lambda` / `let` / `begin`

**内置过程**（spec §5）：

- 算术 `+ - * / modulo quotient expt abs`
- 比较 `= < > <= >=`（链式，如 `(< 2 3 4)`）
- 布尔 `not`
- 列表 `cons car cdr list length append null? pair? list?`
- 谓词 `number? boolean? symbol? string? procedure? zero? even? odd? eq? equal?`
- 输出 `display newline`

**明确不在范围内**（spec §10）：`set!`、`set-car!`/`set-cdr!`、quasiquote、向量、字符、字符串函数、可变参数 lambda、宏、尾调用优化保证。`map`/`filter` **不内置**——按 spec 要求用语言本身定义：

```scheme
(define (map f xs)
  (if (null? xs) '() (cons (f (car xs)) (map f (cdr xs)))))
(map (lambda (x) (* x x)) '(1 2 3 4))   ; → (1 4 9 16)
```

## 仓库结构

```
.
├── src/                    解释器源码（入口 src/main.py，约 1800 行含注释）
├── example/                6 个由易到难的示例，逐行注释标注期望输出
├── tests/                  开发用自测脚本（非交付必需，可删）
├── spec.md                 语言规范（课程提供）
├── TASK.md                 原题说明（课程提供的起始 README 原文）
├── autograder.pyz          官方评分器（课程提供）
├── LICENSE                 MIT
└── README.md
```

> [!NOTE]
> `spec.md`、`example/`、`autograder.pyz` 来自课程 starter 仓库
> [woo114515/minischeme-starter](https://github.com/woo114515/minischeme-starter)，
> 是验收依据，为保证评分器可复现而保留；版权归原作者。本项目的原创部分是 `src/` 与 `tests/`。

## 测试脚本

`tests/` 下的脚本只依赖标准库，都从仓库根目录运行：

```bash
python3 tests/check_examples.py                 # 核对 example/ 里每行注释的期望输出
python3 tests/check_examples.py example/03_functions.scm   # 只核对指定文件
python3 tests/smoke.py                          # 求值、整段程序、出错路径、CLI 约定
python3 tests/check_imports.py                  # 静态检查未定义名/未使用导入
python3 tests/verify_autograder.py              # 独立复核评分器结论
python3 tests/check_readme.py                   # 核对本 README 的行数与示例是否与代码一致
```
