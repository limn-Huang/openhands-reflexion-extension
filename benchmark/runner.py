"""
Benchmark Runner —— 跑单个任务,收集指标。

用法:
    # Baseline (无 Critic)
    uv run python -m benchmark.runner --task task_1 --mode baseline
    
    # With Reflexion
    uv run python -m benchmark.runner --task task_1 --mode with_reflexion

输出:
    benchmark/results/{task_id}_{mode}_{timestamp}.json
    
    并在 console 打印关键指标。
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# 让 benchmark 能 import my_extensions
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

from my_extensions.reflection import create_reflexion_critic
from my_extensions.metrics import collect_metrics, save_metrics

from benchmark.tasks import get_task, verify


RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


def setup_logging(quiet: bool = False):
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_llm() -> LLM:
    return LLM(
        model=os.getenv("LLM_MODEL", "openai/glm-5.1"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        max_output_tokens=4096,
        temperature=0.0,
    )


def build_agent(llm: LLM, mode: str) -> Agent:
    """
    根据 mode 构建 Agent。
    
    - baseline: 不带 critic
    - with_reflexion: 带 ReflexionCritic + max_iter=3
    """
    tools = [
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
    ]
    
    if mode == "baseline":
        return Agent(llm=llm, tools=tools)
    
    elif mode == "with_reflexion":
        critic = create_reflexion_critic(
            llm=llm,
            success_threshold=0.7,
            max_iterations=3,
        )
        return Agent(llm=llm, tools=tools, critic=critic)
    
    else:
        raise ValueError(f"Unknown mode: {mode}")


def run_single_task(task_id: str, mode: str) -> dict:
    """
    跑一次任务,返回完整 metrics。
    """
    logger = logging.getLogger(__name__)
    
    task = get_task(task_id)
    
    print(f"\n{'='*70}")
    print(f"📋 Running: {task.task_id} (difficulty={task.difficulty}, mode={mode})")
    print(f"{'='*70}")
    print(f"Prompt:\n{task.prompt[:300]}...\n")
    
    # 用临时目录,避免污染
    workspace = Path(tempfile.mkdtemp(prefix=f"bench_{task_id}_"))
    print(f"📁 Workspace: {workspace}\n")
    
    # === 构建 Agent + Conversation ===
    llm = build_llm()
    agent = build_agent(llm, mode)
    conversation = Conversation(agent=agent, workspace=str(workspace))
    
    # === 跑任务,计时 ===
    start = time.time()
    
    try:
        conversation.send_message(task.prompt)
        conversation.run()
    except Exception as e:
        logger.error(f"Conversation crashed: {e}", exc_info=True)
    
    duration = time.time() - start
    
    # === 外部 verify(用 subprocess 跑真实命令)===
    print(f"\n🔍 Verifying with: {task.verify_command}")
    verified_ok, verify_msg = verify(task, workspace)
    print(f"   {'✅' if verified_ok else '❌'} {verify_msg[:300]}")
    
    # === 收集 metrics ===
    metrics = collect_metrics(
        conversation=conversation,
        task_id=task_id,
        mode=mode,
        duration_seconds=duration,
        workspace_dir=workspace,
    )
    
    # 用外部 verify 覆盖 success(更可靠)
    metrics["success"] = verified_ok
    metrics["verify_message"] = verify_msg[:500]
    metrics["difficulty"] = task.difficulty
    
    # === 保存 + 打印摘要 ===
    save_path = save_metrics(metrics, RESULTS_DIR)
    
    print(f"\n📊 Metrics Summary:")
    print(f"  Success:           {metrics['success']}")
    print(f"  Reflexion triggered: {metrics['reflexion_triggered']}")
    print(f"  Iterations:        {metrics['iterations']}")
    print(f"  Total actions:     {metrics['total_actions']}")
    print(f"  Critic scores:     {metrics['critic_scores']}")
    print(f"  Duration:          {metrics['duration_seconds']}s")
    print(f"  Token (in/out):    {metrics['token_input']}/{metrics['token_output']}")
    print(f"  Files created:     {metrics['files_created']}")
    print(f"\n💾 Saved to: {save_path}")
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Run benchmark on a single task")
    parser.add_argument("--task", required=True, help="Task ID (task_1 to task_5)")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["baseline", "with_reflexion"],
        help="Run mode",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress INFO logs")
    args = parser.parse_args()
    
    setup_logging(quiet=args.quiet)
    
    run_single_task(args.task, args.mode)


if __name__ == "__main__":
    main()