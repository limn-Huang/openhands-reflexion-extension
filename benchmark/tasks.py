"""
标准测试任务集。

设计原则:
1. **难度梯度**:从"几乎不可能失败"到"baseline 极易漏 edge case"
2. **可自动验证**:每个任务带 verify 函数,无需人工判断
3. **复现性**:都用 deterministic 的输入输出

5 个任务:
- task_1:简单 hello world(基准,几乎不会失败)
- task_2:函数 + CLI + 异常处理(标准 coding task)
- task_3:edge case 题(hyphenated 单词 / 数字不算词)
- task_4:多文件 + 跨文件导入(中等复杂度)
- task_5:测试驱动开发(写代码 + 写单元测试)
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    task_id: str
    difficulty: str  # "easy" / "medium" / "hard"
    prompt: str
    verify_command: str  # 在 workspace 下跑这个命令
    expected_in_stdout: list[str]  # stdout 必须包含这些字符串


def verify(task: Task, workspace: Path) -> tuple[bool, str]:
    """
    在 workspace 下跑 verify_command,检查输出是否符合预期。
    
    Returns:
        (是否通过, 详细信息)
    """
    if not workspace.exists():
        return False, "Workspace does not exist"
    
    try:
        result = subprocess.run(
            task.verify_command,
            shell=True,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout during verification"
    except Exception as e:
        return False, f"Verify command crashed: {e}"
    
    output = result.stdout + result.stderr
    missing = [s for s in task.expected_in_stdout if s not in output]
    
    if missing:
        return False, f"Output missing expected strings: {missing}\n--- Actual output ---\n{output[:1000]}"
    
    if result.returncode != 0 and not task.expected_in_stdout:
        # 没指定 expected 时,看 exit code
        return False, f"Non-zero exit code: {result.returncode}\nOutput: {output[:500]}"
    
    return True, "All checks passed"


# =============================================================================
# 任务定义
# =============================================================================

TASK_1 = Task(
    task_id="task_1",
    difficulty="easy",
    prompt=(
        "Create a Python file `hello.py` that prints exactly:\n"
        "Hello, OpenHands!\n"
        "\n"
        "After creating, run `python hello.py` to verify."
    ),
    verify_command="python hello.py",
    expected_in_stdout=["Hello, OpenHands!"],
)


TASK_2 = Task(
    task_id="task_2",
    difficulty="easy",
    prompt=(
        "Create `calculator.py` with:\n"
        "1. Function `add(a, b)` returning a + b\n"
        "2. Function `divide(a, b)` returning a / b, raising ValueError if b == 0\n"
        "3. CLI: `python calculator.py 5 3` prints both results\n"
        "\n"
        "After creating, run `python calculator.py 5 3` to verify."
    ),
    verify_command="python calculator.py 5 3",
    expected_in_stdout=["8", "1.6666"],
)


TASK_3 = Task(
    task_id="task_3",
    difficulty="medium",
    prompt=(
        "Create `wordcount.py` that:\n"
        "1. Takes a file path from CLI: `python wordcount.py <file>`\n"
        "2. Counts: lines, words, unique_words (case-insensitive)\n"
        "\n"
        "**CRITICAL edge cases:**\n"
        "  - Hyphenated words like 'well-known' count as ONE word\n"
        "  - Pure numbers like '42' or '3.14' are NOT counted as words\n"
        "  - Empty file returns all zeros\n"
        "\n"
        "Print results as: 'Lines: X', 'Words: X', 'Unique words: X' (one per line).\n"
        "\n"
        "Also create `sample.txt` with EXACTLY this content (3 lines):\n"
        "Hello world!\n"
        "This is a well-known test file.\n"
        "Numbers like 42 and 3.14 should not be counted.\n"
        "\n"
        "After creating both files, run `python wordcount.py sample.txt` and verify:\n"
        "  Lines: 3\n"
        "  Words: 15\n"
        "  Unique words: 15\n"
    ),
    verify_command="python wordcount.py sample.txt",
    # 这里特意只检查关键数字,避免格式微差异导致 false negative
    expected_in_stdout=["Lines: 3", "Words: 15", "Unique words: 15"],
)


TASK_4 = Task(
    task_id="task_4",
    difficulty="medium",
    prompt=(
        "Create a small utilities package:\n"
        "1. `utils/math_ops.py` with function `fibonacci(n)` returning the n-th Fibonacci number (0-indexed)\n"
        "   - fibonacci(0) = 0, fibonacci(1) = 1, fibonacci(2) = 1, fibonacci(10) = 55\n"
        "   - Raise ValueError for negative n\n"
        "2. `utils/__init__.py` (empty)\n"
        "3. `demo.py` in the root that imports fibonacci and prints fibonacci(10).\n"
        "\n"
        "After creating, run `python demo.py` to verify output is `55`."
    ),
    verify_command="python demo.py",
    expected_in_stdout=["55"],
)


TASK_5 = Task(
    task_id="task_5",
    difficulty="hard",
    prompt=(
        "Create `string_utils.py` with:\n"
        "1. Function `is_palindrome(s: str) -> bool` that checks if `s` is a palindrome.\n"
        "   - Ignore case and non-alphanumeric characters\n"
        "   - Empty string and single char return True\n"
        "   - Example: 'A man, a plan, a canal: Panama' → True\n"
        "\n"
        "2. Function `count_vowels(s: str) -> int` counting vowels (aeiouAEIOU, no 'y')\n"
        "\n"
        "Then create `test_string_utils.py` with at least 5 pytest test cases covering:\n"
        "  - Basic palindrome\n"
        "  - Palindrome with punctuation\n"
        "  - Non-palindrome\n"
        "  - Vowel counting basic\n"
        "  - Empty string\n"
        "\n"
        "After creating, run `python -m pytest test_string_utils.py -v` and ensure ALL tests pass."
    ),
    verify_command="python -m pytest test_string_utils.py -v",
    expected_in_stdout=["passed", "5 passed"],
)
# =============================================================================
# 困难任务(为 Reflexion 设计 —— baseline 极易在 silent failure / 多 edge case 上栽跟头)
# =============================================================================

TASK_H1 = Task(
    task_id="task_h1",
    difficulty="hard",
    prompt=(
        "Create `range_sum.py` that defines `range_sum(start, end)` and has a CLI.\n"
        "\n"
        "**CRITICAL REQUIREMENT (read carefully):**\n"
        "  `range_sum(start, end)` returns the sum of integers from `start` to `end`,\n"
        "  **INCLUSIVE on BOTH ends**. This means:\n"
        "    - range_sum(1, 10) should return 55 (1+2+3+4+5+6+7+8+9+10)\n"
        "    - range_sum(5, 5) should return 5 (single point)\n"
        "    - range_sum(0, 0) should return 0\n"
        "    - range_sum(-3, 3) should return 0 (-3-2-1+0+1+2+3 = 0)\n"
        "\n"
        "CLI: `python range_sum.py START END` prints the result.\n"
        "\n"
        "After creating, run ALL of these to verify:\n"
        "  python range_sum.py 1 10    (expect: 55)\n"
        "  python range_sum.py 5 5     (expect: 5)\n"
        "  python range_sum.py -3 3    (expect: 0)\n"
        "\n"
        "Verification (run this exact command):\n"
        "  python -c \"from range_sum import range_sum; "
        "assert range_sum(1, 10) == 55; "
        "assert range_sum(5, 5) == 5; "
        "assert range_sum(0, 0) == 0; "
        "assert range_sum(-3, 3) == 0; "
        "print('ALL_PASS')\"\n"
    ),
    verify_command=(
        'python -c "from range_sum import range_sum; '
        'assert range_sum(1, 10) == 55; '
        'assert range_sum(5, 5) == 5; '
        'assert range_sum(0, 0) == 0; '
        'assert range_sum(-3, 3) == 0; '
        'print(\'ALL_PASS\')"'
    ),
    expected_in_stdout=["ALL_PASS"],
)


TASK_H2 = Task(
    task_id="task_h2",
    difficulty="hard",
    prompt=(
        "Create `math_utils.py` with EXACTLY these 3 functions:\n"
        "\n"
        "1. `safe_divide(a, b)`:\n"
        "   - Returns a / b as a float\n"
        "   - Returns None when b == 0 (DO NOT raise)\n"
        "   - Always returns float type (e.g. safe_divide(6, 2) returns 3.0 not 3)\n"
        "\n"
        "2. `clamp(value, low, high)`:\n"
        "   - Returns value clamped to [low, high]\n"
        "   - **If low > high, swap them automatically before clamping**\n"
        "     (i.e. clamp(5, 10, 0) should treat the range as [0, 10] and return 5)\n"
        "\n"
        "3. `is_prime(n)`:\n"
        "   - Returns True if n is prime, else False\n"
        "   - is_prime(2) == True\n"
        "   - is_prime(1) == False (1 is NOT prime)\n"
        "   - is_prime(0) == False\n"
        "   - is_prime(-5) == False (negatives are not prime)\n"
        "\n"
        "Create `test_math_utils.py` with these EXACT assertions:\n"
        "```python\n"
        "from math_utils import safe_divide, clamp, is_prime\n"
        "\n"
        "def test_safe_divide():\n"
        "    assert safe_divide(6, 2) == 3.0\n"
        "    assert isinstance(safe_divide(6, 2), float)\n"
        "    assert safe_divide(5, 0) is None\n"
        "\n"
        "def test_clamp():\n"
        "    assert clamp(5, 0, 10) == 5\n"
        "    assert clamp(15, 0, 10) == 10\n"
        "    assert clamp(5, 10, 0) == 5  # low>high auto-swap\n"
        "\n"
        "def test_is_prime():\n"
        "    assert is_prime(2) == True\n"
        "    assert is_prime(1) == False\n"
        "    assert is_prime(0) == False\n"
        "    assert is_prime(-5) == False\n"
        "```\n"
        "\n"
        "Run `python -m pytest test_math_utils.py -v` — ALL 3 tests must pass.\n"
    ),
    verify_command="python -m pytest test_math_utils.py -v",
    expected_in_stdout=["3 passed"],
)


TASK_H3 = Task(
    task_id="task_h3",
    difficulty="hard",
    prompt=(
        "Create `csv_dedup.py` that reads a CSV and removes duplicate rows.\n"
        "\n"
        "**CRITICAL REQUIREMENTS:**\n"
        "1. CLI: `python csv_dedup.py INPUT OUTPUT`\n"
        "2. **Preserve original row order** — dedup keeps FIRST occurrence of each unique row\n"
        "3. **Dedup is CASE-SENSITIVE** — 'Bob' and 'BOB' are DIFFERENT rows\n"
        "4. Header row is preserved (first line)\n"
        "5. Empty lines are skipped\n"
        "\n"
        "Also create `input.csv` with EXACTLY these 7 lines:\n"
        "```\n"
        "name,age\n"
        "Alice,30\n"
        "Bob,25\n"
        "Alice,30\n"
        "BOB,25\n"
        "Charlie,40\n"
        "```\n"
        "(The line after Bob,25 is a duplicate of Alice,30. BOB,25 is NOT a duplicate of Bob,25 because case differs.)\n"
        "\n"
        "After running `python csv_dedup.py input.csv output.csv`,\n"
        "the output.csv should contain EXACTLY:\n"
        "```\n"
        "name,age\n"
        "Alice,30\n"
        "Bob,25\n"
        "BOB,25\n"
        "Charlie,40\n"
        "```\n"
        "\n"
        "(5 lines total: header + 4 unique data rows, in original first-occurrence order)\n"
        "\n"
        "Verify with this command (do not modify):\n"
        "  python -c \"content=open('output.csv').read().strip().split('\\n'); "
        "assert content == ['name,age', 'Alice,30', 'Bob,25', 'BOB,25', 'Charlie,40'], "
        "f'GOT: {content}'; print('ALL_PASS')\"\n"
    ),
    verify_command=(
        'python -c "content=open(\'output.csv\').read().strip().split(\'\\n\'); '
        "assert content == ['name,age', 'Alice,30', 'Bob,25', 'BOB,25', 'Charlie,40'], "
        "f'GOT: {content}'; print('ALL_PASS')\""
    ),
    expected_in_stdout=["ALL_PASS"],
)

ALL_TASKS = {
    "task_1": TASK_1,
    "task_2": TASK_2,
    # task_3 已知数据异常,排除
    "task_4": TASK_4,
    "task_5": TASK_5,
    # Hard tasks designed for Reflexion
    "task_h1": TASK_H1,
    "task_h2": TASK_H2,
    "task_h3": TASK_H3,
}


def get_task(task_id: str) -> Task:
    if task_id not in ALL_TASKS:
        raise ValueError(f"Unknown task_id: {task_id}. Available: {list(ALL_TASKS.keys())}")
    return ALL_TASKS[task_id]