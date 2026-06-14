"""
Memory Hooks —— 把 SummaryMemory 集成到 OpenHands Conversation。

集成策略(本版本采用"被动调用"方式):
- 提供 maybe_compress_history() 函数,在 example 主循环里手动调用
- 函数检查 EventLog 长度,超过阈值就触发 SummaryMemory.compress()
- 压缩后的 summary 存到 state.agent_state["summary_memory"]
"""

import logging
from typing import Any

from openhands.sdk.conversation import LocalConversation
from openhands.sdk.event.base import LLMConvertibleEvent

from my_extensions.summary_memory import SummaryMemory, AGENT_STATE_KEY

logger = logging.getLogger(__name__)


# =============================================================================
# 默认参数
# =============================================================================

# 当 EventLog 中"LLM 可见事件"达到这个数,触发首次压缩
DEFAULT_COMPRESSION_THRESHOLD = 30

# 后续每多多少个新事件,触发一次增量合并压缩
DEFAULT_INCREMENT_THRESHOLD = 20


# =============================================================================
# 主接口:在 Agent 循环里被调用
# =============================================================================

def maybe_compress_history(
    conversation: LocalConversation,
    summary_memory: SummaryMemory,
    initial_threshold: int = DEFAULT_COMPRESSION_THRESHOLD,
    increment_threshold: int = DEFAULT_INCREMENT_THRESHOLD,
) -> bool:
    """
    判断是否需要压缩历史,需要则压缩。
    
    Returns:
        True if compression happened, False otherwise
    
    用法(在 example 里):
        compressed = maybe_compress_history(conversation, summary_memory)
        if compressed:
            logger.info("History was compressed")
    
    触发逻辑:
    - 首次:LLMConvertibleEvent 数量 >= initial_threshold → 压缩前 N-10 个
    - 后续:已压缩 + 新增的事件数 >= increment_threshold → 合并压缩
    """
    state = conversation.state
    
    # 从 EventLog 取 LLM 可见事件(过滤掉系统内部事件)
    all_events = list(state.events)
    llm_events = [e for e in all_events if isinstance(e, LLMConvertibleEvent)]
    
    if not llm_events:
        return False
    
    # 读取已有 summary(如果有)
    existing_summary = state.agent_state.get(AGENT_STATE_KEY)
    
    # === Case 1: 首次压缩 ===
    if existing_summary is None:
        if len(llm_events) < initial_threshold:
            return False
        
        # 保留最近 10 个 event 不压缩(最近的对 Agent 决策最重要)
        events_to_compress = llm_events[:-10]
        
        logger.info(
            f"[MemoryHook] First compression triggered: "
            f"{len(events_to_compress)} events → summary"
        )
        
        new_summary = summary_memory.compress(events_to_compress)
        _save_summary_to_state(conversation, new_summary)
        return True
    
    # === Case 2: 增量合并 ===
    already_covered = existing_summary.get("covered_event_count", 0)
    
    # 计算新增了多少 event(还没被压缩进 summary 的)
    # 保留最近 10 个不压缩
    new_events_count = len(llm_events) - already_covered - 10
    
    if new_events_count < increment_threshold:
        return False
    
    # 取出"已压缩之后、最近 10 个之前"的新事件
    new_events = llm_events[already_covered : len(llm_events) - 10]
    
    if not new_events:
        return False
    
    logger.info(
        f"[MemoryHook] Incremental compression: "
        f"{len(new_events)} new events to merge into existing summary"
    )
    
    new_summary = summary_memory.merge(existing_summary, new_events)
    _save_summary_to_state(conversation, new_summary)
    return True


def get_current_summary(conversation: LocalConversation) -> dict[str, Any] | None:
    """
    取出当前的 summary(如果有)。
    
    供调试 / 监控用,也可以让其他扩展(比如 prompt 注入器)使用。
    """
    return conversation.state.agent_state.get(AGENT_STATE_KEY)


def _save_summary_to_state(
    conversation: LocalConversation,
    summary: dict[str, Any],
) -> None:
    """
    把 summary 写入 state.agent_state。
    
    使用 OpenHands 官方推荐的"完整重新赋值"模式触发自动持久化:
        state.agent_state = {**state.agent_state, key: value}
    """
    state = conversation.state
    state.agent_state = {
        **state.agent_state,
        AGENT_STATE_KEY: summary,
    }
    logger.info(
        f"[MemoryHook] Summary saved: "
        f"v{summary['version']}, "
        f"covered {summary['covered_event_count']} events, "
        f"method={summary['compression_method']}"
    )


# =============================================================================
# 单元测试:python -m my_extensions.memory_hooks
# =============================================================================

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Hooks 模块 import 测试")
    print("=" * 60)
    
    # 这里不真的跑 conversation,只确认 import 链路正常
    from openhands.sdk.llm import LLM
    
    llm = LLM(
        model=os.getenv("LLM_MODEL", "openai/glm-5.1"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        max_output_tokens=4096,
    )
    
    memory = SummaryMemory(llm=llm)
    print(f"✅ SummaryMemory + Hooks 模块加载成功")
    print(f"   thresholds: initial={DEFAULT_COMPRESSION_THRESHOLD}, "
          f"increment={DEFAULT_INCREMENT_THRESHOLD}")
    print(f"\n💡 真实场景测试将在 Step 5 (端到端 example) 中验证")
