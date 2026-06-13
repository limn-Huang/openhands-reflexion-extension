"""
批量跑所有 task × mode 实验。

用法:
    # 跑全部(5 个任务 × 2 模式 = 10 次)
    uv run python -m benchmark.run_all
    
    # 只跑特定任务
    uv run python -m benchmark.run_all --tasks task_1,task_2
    
    # 只跑特定模式
    uv run python -m benchmark.run_all --modes baseline

设计要点:
1. **失败不中断**:某次跑失败,记录错误继续下一次,不影响整体
2. **进度可见**:每次跑前打印 [N/总数] 进度条
3. **可恢复**:已跑过的 task+mode+timestamp 不会重跑(看 results/ 文件)
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner import run_single_task
from benchmark.tasks import ALL_TASKS


def run_batch(task_ids: list[str], modes: list[str]) -> None:
    """跑批量实验"""
    total = len(task_ids) * len(modes)
    completed = 0
    failed = 0
    
    overall_start = time.time()
    
    print(f"\n{'='*70}")
    print(f"🚀 Batch Benchmark Started")
    print(f"   Tasks: {task_ids}")
    print(f"   Modes: {modes}")
    print(f"   Total runs: {total}")
    print(f"{'='*70}\n")
    
    for task_id in task_ids:
        for mode in modes:
            completed += 1
            
            elapsed = (time.time() - overall_start) / 60
            print(f"\n\n{'#'*70}")
            print(f"# [{completed}/{total}] Running: {task_id} / {mode}")
            print(f"#   Elapsed: {elapsed:.1f}min, Failed so far: {failed}")
            print(f"{'#'*70}\n")
            
            try:
                run_single_task(task_id, mode)
            except KeyboardInterrupt:
                print(f"\n⚠️ User interrupted at [{completed}/{total}]")
                print(f"   Already completed runs are saved in benchmark/results/")
                return
            except Exception as e:
                failed += 1
                print(f"\n❌ FAILED: {task_id} / {mode}: {e}")
                import traceback
                traceback.print_exc()
                print(f"   Continuing with next run...\n")
                continue
    
    overall_duration = (time.time() - overall_start) / 60
    print(f"\n\n{'='*70}")
    print(f"✅ Batch Complete!")
    print(f"   Total: {completed} runs")
    print(f"   Failed: {failed}")
    print(f"   Total time: {overall_duration:.1f} min")
    print(f"{'='*70}\n")
    print(f"📊 Next step: python -m benchmark.analyze")


def main():
    parser = argparse.ArgumentParser(description="Run batch benchmark")
    parser.add_argument(
        "--tasks",
        default=",".join(ALL_TASKS.keys()),
        help="Comma-separated task IDs (default: all)",
    )
    parser.add_argument(
        "--modes",
        default="baseline,with_reflexion",
        help="Comma-separated modes (default: both)",
    )
    args = parser.parse_args()
    
    task_ids = [t.strip() for t in args.tasks.split(",")]
    modes = [m.strip() for m in args.modes.split(",")]
    
    # 验证
    for tid in task_ids:
        if tid not in ALL_TASKS:
            print(f"❌ Unknown task: {tid}")
            sys.exit(1)
    
    for mode in modes:
        if mode not in ("baseline", "with_reflexion"):
            print(f"❌ Unknown mode: {mode}")
            sys.exit(1)
    
    # 加日志
    logging.basicConfig(
        level=logging.WARNING,  # 批量跑用 WARNING 减少干扰
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    run_batch(task_ids, modes)


if __name__ == "__main__":
    main()