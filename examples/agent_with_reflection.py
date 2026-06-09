"""
基于 OpenHands V1 SDK 的 Reflection-Augmented Coding Agent。

这个 example 展示:
1. 如何用 ReflexionCritic 给 OpenHands Agent 加"反思"能力
2. 如何用 SummaryMemory 缓解长任务的 context 膨胀
3. 整套机制"零侵入"接入 SDK 主循环

跑法:
    # 在项目根目录(openhands-enhanced/)下:
    uv run python examples/agent_with_reflection.py

环境要求(.env):
    LLM_MODEL=openai/glm-5.1
    LLM_API_KEY=你的GLM_API_KEY
    LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
"""

import logging
import os
import sys
from pathlib import Path

# 让 example 能 import my_extensions(因为 example 在 examples/ 目录里跑)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

from my_extensions.reflection import create_reflexion_critic
from my_extensions.summary_memory import SummaryMemory
from my_extensions.memory_hooks import maybe_compress_history, get_current_summary


# =============================================================================
# 日志配置:让我们能清楚看到每个组件何时被触发
# =============================================================================

def setup_logging():
    """配置日志输出 —— 重点突出我们的扩展模块"""
    Path("logs").mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/agent_with_reflection.log", encoding="utf-8"),
        ],
    )
    
    # 我们自己的扩展模块用更显眼的 INFO 级别
    logging.getLogger("my_extensions").setLevel(logging.INFO)


# =============================================================================
# 主流程
# =============================================================================

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 70)
    logger.info("OpenHands + Reflexion Critic + Summary Memory")
    logger.info("=" * 70)
    
    # === Step 1: 创建 LLM ===
    llm = LLM(
        model=os.getenv("LLM_MODEL", "openai/glm-5.1"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        max_output_tokens=4096,   # Day 3 踩过的坑:思考模型必须 4096+
        temperature=0.0,
    )
    logger.info(f"LLM 模型: {llm.model}")
    
    # === Step 2: 创建 Reflexion Critic ===
    # 关键设计:Critic 用同一个 LLM(也可以换便宜模型省钱)
    critic = create_reflexion_critic(
        llm=llm,
        success_threshold=0.7,   # 任务"成功"的分数线
        max_iterations=3,        # 最多反思 3 次(成本控制,生产可调高)
    )
    logger.info(
        f"Reflexion Critic: threshold={critic.iterative_refinement.success_threshold}, "
        f"max_iter={critic.iterative_refinement.max_iterations}"
    )
    
    # === Step 3: 创建 Summary Memory ===
    summary_memory = SummaryMemory(llm=llm)
    logger.info(f"Summary Memory: ready")
    
    # === Step 4: 创建 Agent(带 Critic)===
    agent = Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
        ],
        critic=critic,   # ⭐ 关键:把 Critic 挂到 Agent
    )
    logger.info("Agent created with Reflexion Critic attached")
    
    # === Step 5: 创建工作空间 ===
    # 用一个临时目录作为 workspace,避免污染项目根目录
    workspace_dir = PROJECT_ROOT / "workspace_demo"
    workspace_dir.mkdir(exist_ok=True)
    
    conversation = Conversation(
        agent=agent,
        workspace=str(workspace_dir),
    )
    logger.info(f"Workspace: {workspace_dir}")
    
    # === Step 6: 发送任务 ===
    # 选一个"有点复杂、容易第一次失败"的任务,让我们能看到 Reflection 工作
    task = (
    "Create `wordcount.py` that:\n"
    "1. Reads a text file passed as CLI argument\n"
    "2. Counts: lines, words, unique_words (case-insensitive), and chars\n"
    "3. Hyphenated words ('well-known') count as 1 word\n"
    "4. Numbers like '42' and '3.14' are NOT counted as words\n"  
    "5. Print each on its own line: 'Lines: X', 'Words: X' etc\n"
    "\n"
    "Then create a sample.txt with 'Hello world\\nThis is well-known\\n42 is a number'\n"
    "Run wordcount.py sample.txt and verify the output matches:\n"
    "  Lines: 3\n  Words: 7\n  Unique words: 7\n  Chars: ~50\n"
)
    
    logger.info("\n" + "=" * 70)
    logger.info("📨 Task to Agent:")
    logger.info(task)
    logger.info("=" * 70 + "\n")
    
    conversation.send_message(task)
    
    # === Step 7: 运行 Agent(SDK 会自动用 Critic 做迭代精炼) ===
    logger.info("🚀 Agent 开始执行...(可能耗时 2-5 分钟,取决于任务复杂度和 LLM 速度)")
    
    try:
        conversation.run()
    except Exception as e:
        logger.error(f"Conversation crashed: {e}", exc_info=True)
    
    # === Step 8: 跑完后,手动触发一次 Summary 压缩(展示用)===
    # 真实场景里,这会在 Hook 自动触发(Day 6 升级);今天先手动调
    logger.info("\n" + "=" * 70)
    logger.info("📦 检查是否需要压缩历史...")
    logger.info("=" * 70)
    
    # 用低阈值强制触发一次,方便你看效果
    compressed = maybe_compress_history(
        conversation,
        summary_memory,
        initial_threshold=5,    # 故意调低,确保触发(平时 30)
    )
    
    if compressed:
        summary = get_current_summary(conversation)
        logger.info(f"✅ 历史已压缩为 summary:")
        logger.info(f"   覆盖事件数: {summary['covered_event_count']}")
        logger.info(f"   版本: v{summary['version']}")
        logger.info(f"   方法: {summary['compression_method']}")
        logger.info(f"\n📝 Summary 内容:\n{summary['summary']}\n")
    else:
        logger.info("ℹ️  事件数不够,未触发压缩")
    
    # === Step 9: 总结报告 ===
    logger.info("\n" + "=" * 70)
    logger.info("📊 执行总结")
    logger.info("=" * 70)
    
    state = conversation.state
    all_events = list(state.events)
    
    logger.info(f"总事件数: {len(all_events)}")
    logger.info(f"执行状态: {state.execution_status}")
    
    # 检查是否经历了 iterative refinement
    iteration_count = state.agent_state.get("iterative_refinement_iteration", 0)
    if iteration_count > 0:
        logger.info(f"🔁 Reflexion 触发次数: {iteration_count}")
        logger.info(
            "   → 这意味着 Agent 至少失败了一次,"
            "Critic 给了低分,Agent 基于反思重新尝试"
        )
    else:
        logger.info("✨ Agent 一次性完成任务,无需 Reflexion")
    
    logger.info(f"\n📂 检查输出文件: {workspace_dir}")
    
    # 列出 workspace 里生成的文件
    if workspace_dir.exists():
        files = list(workspace_dir.iterdir())
        logger.info(f"Workspace 内容 ({len(files)} 项):")
        for f in files:
            logger.info(f"  - {f.name}")
    
    logger.info("\n✅ Example 结束")


if __name__ == "__main__":
    main()