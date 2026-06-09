"""
SummaryMemory —— 把 EventLog 历史压缩成简短摘要,缓解 context 膨胀。

为什么不直接删 EventLog 里的 event?
1. EventLog 是审计日志,设计上不该被破坏(可重放、可调试、可恢复)
2. OpenHands 用 FIFOLock 保护 EventLog,直接改它有并发风险
3. 删了就回不来 —— 但 summary 失败时我们需要回退到原始事件

我们的做法:
- EventLog 保持不变(SDK 自动持久化)
- 在 state.agent_state["summary_memory"] 存压缩后的摘要
- 用 hook 在合适时机触发压缩(比如 event 数超过阈值)
- 后续可以由别的扩展(比如 Memory 注入器)用这个 summary 替换 prompt 里的早期事件

存储结构(state.agent_state["summary_memory"]):
{
    "summary": "压缩后的文本摘要",
    "covered_event_count": 30,         # 这个 summary 覆盖了多少个早期事件
    "version": 2,                      # 压缩了几次(每次新增 event 多了再压一次)
    "last_compressed_at": "..."        # 最后压缩时间
}
"""

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from openhands.sdk.event.base import LLMConvertibleEvent
from openhands.sdk.llm import LLM, Message, TextContent

from my_extensions.prompts import SUMMARY_SYSTEM, SUMMARY_USER_TEMPLATE

logger = logging.getLogger(__name__)


# agent_state 里我们用的 key
AGENT_STATE_KEY = "summary_memory"


def _events_to_text_for_summary(
    events: Sequence[LLMConvertibleEvent],
    max_chars_per_event: int = 800,
) -> str:
    """
    把 events 转为压缩用的文本。
    
    每个 event 截断到 800 字符——避免长输出(比如 cat 一个大文件)主导 summary
    """
    lines = []
    for i, event in enumerate(events, 1):
        try:
            msg = event.to_llm_message()
            content = getattr(msg, "content", str(msg))
            if len(content) > max_chars_per_event:
                content = content[:max_chars_per_event] + "...[truncated]"
            event_type = type(event).__name__
            lines.append(f"### Event {i} [{event_type}]\n{content}")
        except Exception as e:
            logger.debug(f"Failed to convert event {i}: {e}")
            lines.append(f"### Event {i}\n{str(event)[:max_chars_per_event]}")
    return "\n\n".join(lines)


class SummaryMemory:
    """
    Event 流压缩器。
    
    用法:
        memory = SummaryMemory(llm=critic_llm)
        
        # 在 hook 里调用
        if should_compress(state):
            summary_data = memory.compress(events_to_compress)
            state.agent_state = {
                **state.agent_state,
                "summary_memory": summary_data,
            }
    
    设计要点:
    1. **无状态类**:不持有 agent_state,只负责"输入 events,输出 summary"
    2. **失败降级**:LLM 失败时返回简化的元信息摘要,不让 hook 流程崩溃
    3. **增量压缩**:后续可以扩展为"已有 summary + 新 events → 新 summary"
    """
    
    def __init__(self, llm: LLM, max_tokens: int = 2048):
        """
        Args:
            llm: 用于压缩的 LLM(建议用便宜模型,压缩不需要太强的推理)
            max_tokens: 压缩输出的最大 token(对应约 300-500 字摘要)
        """
        self.llm = llm
        self.max_tokens = max_tokens
    
    def compress(
        self,
        events: Sequence[LLMConvertibleEvent],
    ) -> dict[str, Any]:
        """
        把一组 events 压缩成 summary。
        
        返回 dict 而不是字符串,因为我们要存元信息(版本、时间、覆盖范围)。
        """
        if not events:
            return self._empty_summary()
        
        logger.info(f"[SummaryMemory] Compressing {len(events)} events...")
        
        events_text = _events_to_text_for_summary(events)
        
        try:
            messages = [
                Message(role="system", content=[TextContent(text=SUMMARY_SYSTEM)]),
                Message(
                    role="user",
                    content=[TextContent(
                        text=SUMMARY_USER_TEMPLATE.format(events_text=events_text)
                    )],
                ),
            ]
            
            llm_response = self.llm.completion(messages=messages)
            response_message = llm_response.message
            summary_text = "".join(
                c.text for c in response_message.content
                if hasattr(c, "text")
            ).strip()
            
            if not summary_text:
                logger.warning("[SummaryMemory] LLM returned empty, using fallback")
                return self._fallback_summary(events, reason="empty LLM response")
            
            return {
                "summary": summary_text,
                "covered_event_count": len(events),
                "version": 1,
                "last_compressed_at": datetime.now(timezone.utc).isoformat(),
                "compression_method": "llm",
            }
        
        except Exception as e:
            logger.error(f"[SummaryMemory] LLM call failed: {e}", exc_info=True)
            return self._fallback_summary(events, reason=str(e))
    
    def merge(
        self,
        previous_summary: dict[str, Any],
        new_events: Sequence[LLMConvertibleEvent],
    ) -> dict[str, Any]:
        """
        增量压缩:已有 summary + 新 events → 新 summary。
        
        生产场景下事件持续增长,不能每次都从头压缩(成本太高)。
        策略:把旧 summary 当成"第 0 个事件",和新事件一起喂给 LLM。
        """
        if not new_events:
            return previous_summary
        
        prev_text = previous_summary.get("summary", "")
        prev_count = previous_summary.get("covered_event_count", 0)
        
        # 把 previous_summary 当作"上下文背景",新事件继续压缩
        new_events_text = _events_to_text_for_summary(new_events)
        merged_text = (
            f"# 之前的工作摘要(已发生 {prev_count} 个事件)\n\n"
            f"{prev_text}\n\n"
            f"# 新发生的事件\n\n"
            f"{new_events_text}"
        )
        
        try:
            messages = [
                Message(role="system", content=[TextContent(text=SUMMARY_SYSTEM)]),
                Message(
                    role="user",
                    content=[TextContent(
                        text=SUMMARY_USER_TEMPLATE.format(events_text=merged_text)
                    )],
                ),
            ]
            
            llm_response = self.llm.completion(messages=messages)
            response_message = llm_response.message
            new_text = "".join(
                c.text for c in response_message.content
                if hasattr(c, "text")
            ).strip()
            
            if not new_text:
                return self._fallback_summary(new_events, reason="merge empty response")
            
            return {
                "summary": new_text,
                "covered_event_count": prev_count + len(new_events),
                "version": previous_summary.get("version", 1) + 1,
                "last_compressed_at": datetime.now(timezone.utc).isoformat(),
                "compression_method": "llm_merge",
            }
        
        except Exception as e:
            logger.error(f"[SummaryMemory] Merge failed: {e}", exc_info=True)
            return self._fallback_summary(new_events, reason=f"merge error: {e}")
    
    def _empty_summary(self) -> dict[str, Any]:
        return {
            "summary": "",
            "covered_event_count": 0,
            "version": 0,
            "last_compressed_at": datetime.now(timezone.utc).isoformat(),
            "compression_method": "empty",
        }
    
    def _fallback_summary(
        self,
        events: Sequence[LLMConvertibleEvent],
        reason: str,
    ) -> dict[str, Any]:
        """
        LLM 失败时的降级摘要:列出事件类型计数,至少给后续 hook 一个"我知道压缩失败了"的信号。
        """
        type_counts: dict[str, int] = {}
        for event in events:
            event_type = type(event).__name__
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
        
        type_summary = ", ".join(f"{t}={n}" for t, n in type_counts.items())
        
        return {
            "summary": f"[Fallback: {reason}] 共 {len(events)} 个事件,类型分布: {type_summary}",
            "covered_event_count": len(events),
            "version": 1,
            "last_compressed_at": datetime.now(timezone.utc).isoformat(),
            "compression_method": "fallback",
            "fallback_reason": reason,
        }


# =============================================================================
# 单元测试:python -m my_extensions.summary_memory
# =============================================================================

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Test 1: 实例化 SummaryMemory")
    print("=" * 60)
    
    llm = LLM(
        model=os.getenv("LLM_MODEL", "openai/glm-5.1"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        max_output_tokens=4096,
    )
    
    memory = SummaryMemory(llm=llm)
    print(f"✅ SummaryMemory created: max_tokens={memory.max_tokens}")
    
    print("\n" + "=" * 60)
    print("Test 2: 空 events 压缩")
    print("=" * 60)
    result = memory.compress([])
    print(f"Empty compress result: {result}")
    assert result["covered_event_count"] == 0
    print("✅ 空压缩降级正常")
    
    print("\n" + "=" * 60)
    print("Test 3: Fallback summary(不调 LLM)")
    print("=" * 60)
    
    # 用 mock event 测 fallback(不调 LLM)
    class MockEvent:
        def to_llm_message(self):
            class Msg:
                content = "mock event content"
            return Msg()
    
    fake_events = [MockEvent() for _ in range(3)]
    fallback = memory._fallback_summary(fake_events, reason="test")
    print(f"Fallback: {fallback}")
    assert fallback["compression_method"] == "fallback"
    print("✅ Fallback 机制正常")
    
    print("\n✅ 全部基础测试通过")
    print("\n💡 提示:实际 compress() 真实调 LLM 的测试,在 Step 5 的端到端跑通时验证")