"""
Metrics Collector —— 从 Conversation 跑完后的状态收集关键指标。

设计要点:
1. 纯数据提取,不调 LLM
2. 失败容错:某个字段拿不到不影响整体
3. 输出标准化 dict,可序列化为 JSON
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from openhands.sdk.conversation import LocalConversation
from openhands.sdk.event import ActionEvent

from my_extensions.summary_memory import AGENT_STATE_KEY as SUMMARY_KEY

logger = logging.getLogger(__name__)

# OpenHands 官方的 iterative refinement 计数器 key
ITERATIVE_REFINEMENT_KEY = "iterative_refinement_iteration"


def collect_metrics(
    conversation: LocalConversation,
    task_id: str,
    mode: str,
    duration_seconds: float,
    workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """
    从一次 Conversation 跑完的状态收集指标。
    
    Args:
        conversation: 跑完的 Conversation 实例
        task_id: 任务标识(用于汇总报告)
        mode: "baseline" 或 "with_reflexion"
        duration_seconds: 任务实际耗时
        workspace_dir: 工作目录(用于检查 Agent 创建了什么文件)
    
    Returns:
        包含所有关键指标的 dict
    """
    state = conversation.state
    all_events = list(state.events)
    
    # === Reflexion 相关 ===
    iteration_count = state.agent_state.get(ITERATIVE_REFINEMENT_KEY, 0)
    reflexion_triggered = iteration_count > 0
    
    # 从 events 提取所有 Critic scores
    critic_scores = _extract_critic_scores(all_events)
    
    # === Token 消耗(从 LLM metrics 拿)===
    try:
        llm_metrics = conversation.agent.llm.metrics
        token_input = llm_metrics.accumulated_token_usage.prompt_tokens
        token_output = llm_metrics.accumulated_token_usage.completion_tokens
        cost_usd = llm_metrics.accumulated_cost
    except Exception as e:
        logger.warning(f"Could not fetch LLM metrics: {e}")
        token_input = 0
        token_output = 0
        cost_usd = 0.0
    
    # === 任务成功判定 ===
    # 简单策略:看最终 execution_status,FINISHED 即成功
    # 真实任务里我们还会通过外部 verify 验证(下个文件 tasks.py 提供)
    execution_status = str(state.execution_status)
    success_by_status = "FINISHED" in execution_status
    
    # === 创建的文件 ===
    files_created = []
    if workspace_dir and workspace_dir.exists():
        for f in workspace_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                rel = f.relative_to(workspace_dir)
                files_created.append(str(rel))
    
    # === 步骤数(ActionEvent 数量约等于"Agent 干了多少步")===
    total_actions = sum(1 for e in all_events if isinstance(e, ActionEvent))
    
    # === SummaryMemory 状态 ===
    summary_data = state.agent_state.get(SUMMARY_KEY)
    has_summary = summary_data is not None and summary_data.get("covered_event_count", 0) > 0
    
    return {
        "task_id": task_id,
        "mode": mode,
        "timestamp": datetime.now().isoformat(),
        
        # 核心指标
        "success": success_by_status,
        "execution_status": execution_status,
        
        # Reflexion 指标
        "reflexion_triggered": reflexion_triggered,
        "iterations": iteration_count,
        "critic_scores": critic_scores,
        "final_critic_score": critic_scores[-1] if critic_scores else None,
        
        # 工作量指标
        "total_events": len(all_events),
        "total_actions": total_actions,
        "duration_seconds": round(duration_seconds, 2),
        
        # 成本指标
        "token_input": token_input,
        "token_output": token_output,
        "token_total": token_input + token_output,
        "cost_usd": round(cost_usd, 6),
        
        # 副产物
        "files_created": files_created,
        "has_summary": has_summary,
    }


def _extract_critic_scores(events) -> list[float]:
    """
    从 ActionEvent 里提取所有 Critic 的 score。
    
    OpenHands V1 SDK 把 Critic 评估结果存在 ActionEvent.critic_result。
    """
    scores = []
    for event in events:
        if isinstance(event, ActionEvent):
            critic_result = getattr(event, "critic_result", None)
            if critic_result is not None:
                score = getattr(critic_result, "score", None)
                if score is not None:
                    scores.append(round(float(score), 3))
    return scores


def save_metrics(metrics: dict[str, Any], output_dir: Path) -> Path:
    """保存指标到 JSON,文件名 = task_id + mode + 时间戳"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{metrics['task_id']}_{metrics['mode']}_{timestamp}.json"
    path = output_dir / filename
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    
    logger.info(f"[Metrics] Saved: {path}")
    return path


def load_all_metrics(output_dir: Path) -> list[dict]:
    """加载目录下所有 metrics JSON(用于汇总报告,下一段会用)"""
    if not output_dir.exists():
        return []
    
    all_metrics = []
    for json_file in output_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                all_metrics.append(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load {json_file}: {e}")
    
    return all_metrics


# =============================================================================
# 单测
# =============================================================================

if __name__ == "__main__":
    print("[Metrics] Module loaded. Import collect_metrics, save_metrics from here.")