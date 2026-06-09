"""
ReflexionCritic —— 基于 Reflexion 论文的 OpenHands Critic 实现。

设计思路:
论文 Reflexion (Shinn et al., 2023) 提出 Verbal Reinforcement Learning:
  失败 → 反思失败原因 → 生成文字 lesson → 注入下次尝试 prompt

OpenHands V1 SDK 通过 CriticBase + IterativeRefinementConfig 提供了
天然的实现框架:
  Agent.run() → FinishAction → Critic.evaluate() → score 不够 → followup → retry

我们要做的是:
1. 继承 CriticBase
2. 实现 evaluate(): 调 LLM 给当前 conversation 打分 + 生成 lessons
3. 覆写 get_followup_prompt(): 把 lessons 注入下次 prompt(Verbal Reinforcement 核心)

参考:
- Reflexion 论文: https://arxiv.org/abs/2303.11366
- OpenHands CriticBase: openhands-sdk/openhands/sdk/critic/base.py
"""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from pydantic import Field

from openhands.sdk.critic.base import CriticBase, IterativeRefinementConfig
from openhands.sdk.critic.result import CriticResult
from openhands.sdk.event.base import LLMConvertibleEvent
from openhands.sdk.llm import LLM, Message, TextContent

from my_extensions.prompts import (
    REFLECTION_CRITIC_SYSTEM,
    REFLECTION_CRITIC_USER_TEMPLATE,
    REFLEXION_FOLLOWUP_TEMPLATE,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON(去 markdown 包裹)。Day 2 踩过的坑。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _events_to_text(events: Sequence[LLMConvertibleEvent], max_events: int = 30) -> str:
    """
    把 events 转成给 LLM 看的文本格式。
    
    为什么限制 max_events?
    - 长任务可能 100+ event,全部塞进 prompt token 爆炸
    - 取最近 N 个就够 critic 判断(成功的 task 通常最后几步是验证)
    - 如果有 SummaryMemory(下个文件),早期 events 已被压缩
    """
    if len(events) > max_events:
        prefix = f"[前 {len(events) - max_events} 个事件已省略]\n\n"
        events = list(events)[-max_events:]
    else:
        prefix = ""

    lines = []
    for i, event in enumerate(events, 1):
        # LLMConvertibleEvent 有 to_llm_message() 方法 —— SDK 官方接口
        try:
            msg = event.to_llm_message()
            content = getattr(msg, "content", str(msg))
            event_type = type(event).__name__
            lines.append(f"## Event {i} [{event_type}]\n{content}\n")
        except Exception as e:
            logger.debug(f"Failed to convert event {i}: {e}")
            lines.append(f"## Event {i}\n{event}\n")

    return prefix + "\n".join(lines)


class ReflexionCritic(CriticBase):
    """
    基于 Reflexion 论文的 Critic 实现。
    
    用法:
        critic = ReflexionCritic(
            llm=my_llm,
            iterative_refinement=IterativeRefinementConfig(
                success_threshold=0.7,
                max_iterations=3,
            ),
        )
        agent = Agent(llm=llm, tools=tools, critic=critic)
    
    工作机制:
    1. Agent 执行任务 → 走到 FinishAction
    2. SDK 自动调用 critic.evaluate(events) → CriticResult
    3. SDK 检查 result.score:
       - score >= threshold → 任务结束 ✅
       - score < threshold → 调 critic.get_followup_prompt() → 注入新 prompt 重新跑
    4. 最多迭代 max_iterations 次
    """
    
    # === 继承 CriticBase 后必须保留的字段(Pydantic 会校验)===
    # 这两个字段父类已经定义,我们用默认值即可
    # mode 默认 "finish_and_message" 已经够用
    
    # === 我们自己的扩展字段 ===
    llm: LLM = Field(
        description="用于评估的 LLM(可以和 Agent 用同一个,也可以用更便宜的小模型省钱)"
    )
    
    # Pydantic v2 配置:允许 LLM 这种复杂对象作为字段
    model_config = {"arbitrary_types_allowed": True}
    
    def evaluate(
        self,
        events: Sequence[LLMConvertibleEvent],
        git_patch: str | None = None,
    ) -> CriticResult:
        """
        评估 Agent 的工作质量。
        
        输入:
            events: 整个 conversation 的 LLMConvertibleEvent 序列
            git_patch: 代码改动 diff(可选,这里暂时不用)
        
        输出:
            CriticResult,包含 score(0-1)和 message
        """
        logger.info(f"[ReflexionCritic] Evaluating {len(events)} events...")
        
        events_text = _events_to_text(events, max_events=30)
        user_prompt = REFLECTION_CRITIC_USER_TEMPLATE.format(
            n_events=min(len(events), 30),
            events_text=events_text,
        )
        
        # === 调 LLM 评估 ===
        try:
            # 用 SDK 原生 Message + TextContent,不要传 dict
            messages = [
                Message(
                    role="system",
                    content=[TextContent(text=REFLECTION_CRITIC_SYSTEM)],
                ),
                Message(
                    role="user",
                    content=[TextContent(text=user_prompt)],
                ),
            ]
            
            llm_response = self.llm.completion(messages=messages)
            
            # LLM.completion 返回 LLMResponse,真实文本在 .message.content
            # content 是 list[TextContent | ImageContent...],我们取 text 部分
            response_message = llm_response.message
            raw_text = "".join(
                c.text for c in response_message.content
                if hasattr(c, "text")
            ).strip()
            
            if not raw_text:
                logger.warning("[ReflexionCritic] LLM returned empty (max_tokens?)")
                return self._fallback_result(reason="LLM returned empty response")
            
            logger.info(f"[ReflexionCritic] LLM response: {raw_text[:200]!r}...")
            return self._parse_critic_result(raw_text)
        
        except Exception as e:
            logger.error(f"[ReflexionCritic] LLM call failed: {e}", exc_info=True)
            return self._fallback_result(reason=f"LLM error: {e}")
    
    def _parse_critic_result(self, raw_text: str) -> CriticResult:
        """解析 LLM 输出为 CriticResult。失败则降级。"""
        try:
            cleaned = _extract_json(raw_text)
            data = json.loads(cleaned)
            
            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))  # 限制到 [0, 1]
            
            return CriticResult(
                score=score,
                message=data.get("message", "Evaluation complete"),
                metadata={
                    "issues": data.get("issues", []),
                    "lessons": data.get("lessons", []),
                },
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"[ReflexionCritic] Parse failed: {e}, raw: {raw_text[:200]!r}")
            return self._fallback_result(reason=f"Parse error: {e}")
    
    def _fallback_result(self, reason: str) -> CriticResult:
        """
        Fallback 策略:
        - 解析/调用失败时返回 score=0.5(模糊判断,既不立刻 stop 也不疯狂 retry)
        - message 写明失败原因,便于 debug
        - 不抛异常 —— Critic 失败不能影响 Agent 主流程
        """
        return CriticResult(
            score=0.5,
            message=f"[Critic Fallback] {reason}",
            metadata={"fallback": True},
        )
    
    def get_followup_prompt(
        self, critic_result: CriticResult, iteration: int
    ) -> str:
        """
        覆写父类方法:生成 Reflexion 风格的 followup prompt。
        
        这就是 Reflexion 论文里 "Verbal Reinforcement Learning" 的核心:
        - 不更新模型权重
        - 把 critic 找到的 issues 和 lessons 转成文字
        - 注入下一轮 Agent prompt,作为"教训"
        - Agent 看到这些教训,自然会调整策略
        """
        # 提取上次评估的 issues 和 lessons
        meta = critic_result.metadata or {}
        issues = meta.get("issues", []) or ["(未识别出具体问题)"]
        lessons = meta.get("lessons", []) or ["(未提炼出明确教训)"]
        
        issues_text = "\n".join(f"- {issue}" for issue in issues)
        lessons_text = "\n".join(f"- {lesson}" for lesson in lessons)
        
        return REFLEXION_FOLLOWUP_TEMPLATE.format(
            iteration=iteration,
            score_percent=critic_result.score * 100,
            message=critic_result.message or "(no message)",
            issues_text=issues_text,
            lessons_text=lessons_text,
        )


# =============================================================================
# 工厂函数(便于在示例中创建)
# =============================================================================

def create_reflexion_critic(
    llm: LLM,
    success_threshold: float = 0.7,
    max_iterations: int = 3,
) -> ReflexionCritic:
    """
    创建一个带 iterative refinement 的 Reflexion Critic。
    
    Args:
        llm: 用于评估的 LLM(建议用和 Agent 同样或更便宜的模型)
        success_threshold: 达到这个分数才认为任务成功
        max_iterations: 最多迭代几次
    """
    return ReflexionCritic(
        llm=llm,
        iterative_refinement=IterativeRefinementConfig(
            success_threshold=success_threshold,
            max_iterations=max_iterations,
        ),
    )


# =============================================================================
# 单元测试:python -m my_extensions.reflection
# =============================================================================

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    # 测试 1:能否实例化
    print("=" * 60)
    print("Test 1: 实例化 ReflexionCritic")
    print("=" * 60)
    
    llm = LLM(
        model=os.getenv("LLM_MODEL", "openai/glm-5.1"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        max_output_tokens=4096,
    )
    
    critic = create_reflexion_critic(
        llm=llm,
        success_threshold=0.7,
        max_iterations=3,
    )
    print(f"✅ Critic 创建成功: mode={critic.mode}")
    print(f"   threshold={critic.iterative_refinement.success_threshold}")
    print(f"   max_iter={critic.iterative_refinement.max_iterations}")
    
    # 测试 2:get_followup_prompt 不调 LLM,纯字符串拼接,先单测
    print("\n" + "=" * 60)
    print("Test 2: get_followup_prompt (不调 LLM)")
    print("=" * 60)
    
    fake_result = CriticResult(
        score=0.4,
        message="Task incomplete: file not created",
        metadata={
            "issues": ["File add.py was not created", "Function returns wrong type"],
            "lessons": ["Always verify with `ls` after create", "Read user spec carefully"],
        },
    )
    
    followup = critic.get_followup_prompt(fake_result, iteration=1)
    print(followup)
    print("✅ Followup prompt 生成成功")
    
    print("\n✅ 全部测试通过")