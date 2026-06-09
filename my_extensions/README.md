# my_extensions — OpenHands V1 SDK 非侵入式扩展 / Non-Invasive Extensions for OpenHands V1 SDK

> **定位**:在不修改 OpenHands 源码的前提下,通过继承官方 SDK 的扩展点,为 Agent 添加 Reflexion 风格的自我反思和长上下文压缩能力。所有组件均可对接任意 OpenAI 兼容的 LLM。

---

## 目录结构 / File Layout

```
my_extensions/
├── reflection.py      # ReflexionCritic —— 基于 Reflexion 论文的 Critic 实现
├── summary_memory.py  # SummaryMemory   —— EventLog 历史压缩器
├── memory_hooks.py    # maybe_compress_history() —— 主循环集成接口
├── prompts.py         # 所有 prompt 模板集中管理
└── __init__.py
```

---

## 核心组件 / Core Components

### 1. `ReflexionCritic` — 论文级 Verbal Reinforcement

**设计思路**:Reflexion 论文(Shinn et al., 2023)提出"不更新权重,通过文字教训驱动 Agent 改进"。OpenHands V1 SDK 的 `CriticBase + IterativeRefinementConfig` 天然契合这一框架:

```
Agent.run() → FinishAction → Critic.evaluate() → score < threshold → followup prompt → retry
```

`ReflexionCritic` 做了两件事:

- **`evaluate(events)`**:调用 LLM,对 conversation 历史打分(0–1),同时提取 `issues`(问题)和 `lessons`(教训),以 JSON 返回 `CriticResult`。
- **`get_followup_prompt(result, iteration)`**:覆写父类方法,把 `issues` 和 `lessons` 组装成结构化反思 prompt,注入下一轮 Agent 执行——这是 Reflexion 的核心"verbal reinforcement"步骤。

评估维度(prompt 里定义):任务完成度 40%、代码质量 20%、执行可靠性 20%、效率 10%、验证充分性 10%。

**容错设计**:LLM 调用或 JSON 解析失败时返回 `score=0.5`(不中断主流程,也不无限 retry)。

---

### 2. `SummaryMemory` — 无损上下文压缩

**设计思路**:长任务会产生数百个 event,直接塞进 LLM prompt 会导致 token 爆炸。但直接删除 EventLog 有三个风险:
- EventLog 是审计日志,设计上不可破坏(可重放、可调试);
- OpenHands 用 `FIFOLock` 保护它,并发修改有风险;
- 删了就没有回退路径。

**实际做法**:EventLog 保持不变,只在 `state.agent_state["summary_memory"]` 存摘要元数据:

```json
{
  "summary": "压缩后的文本摘要",
  "covered_event_count": 30,
  "version": 2,
  "last_compressed_at": "2025-...",
  "compression_method": "llm_merge"
}
```

两个方法:
- **`compress(events)`**:首次全量压缩,每个 event 截断至 800 字符防止长输出主导摘要。
- **`merge(previous_summary, new_events)`**:增量压缩,把旧 summary 当作"第 0 个事件"与新事件合并,避免每次从头压缩(控制成本)。

`SummaryMemory` 是无状态类,只负责"输入 events → 输出 summary dict",不持有 `agent_state`,便于单元测试。

---

### 3. `memory_hooks` — 主循环集成层

提供 `maybe_compress_history(conversation, summary_memory)` 一个函数,在示例主循环中手动调用:

- **首次**:LLM 可见事件数 ≥ 30 → 压缩最早的 N-10 个(保留最近 10 个给 Agent 决策);
- **后续**:新增事件数 ≥ 20 → 触发增量 `merge()`。

写入 state 时使用 OpenHands 官方推荐的完整重新赋值模式以触发自动持久化:

```python
state.agent_state = {**state.agent_state, AGENT_STATE_KEY: summary}
```

---

### 4. `prompts.py` — 集中 Prompt 管理

所有 prompt 模板集中在一个文件,用普通字符串 `.format()` 替换,不引入 Jinja 等额外依赖。每个模板标注了"输入 / 期望输出",便于独立调优。

---

## 与官方 APIBasedCritic 的差异 / vs. Official APIBasedCritic

| 维度 | 官方 `APIBasedCritic` | 本项目 `ReflexionCritic` |
|---|---|---|
| LLM 依赖 | All-Hands 商业服务(需账户) | 任意 OpenAI 兼容端点(本地 / 第三方) |
| Reflexion 能力 | 无 `get_followup_prompt` 覆写 | 完整 Verbal Reinforcement 循环 |
| 评估维度 | 服务侧定义,不透明 | prompt 明文定义,可自定义权重 |
| 容错 | 不明 | fallback → score=0.5,不中断流程 |
| 修改方式 | 需 fork 源码 | 继承扩展,零侵入 |

---

## 快速开始 / Quick Start

**环境要求**:OpenHands V1 SDK 已安装,`.env` 文件中配置 LLM 参数。

```python
import os
from dotenv import load_dotenv
load_dotenv()

from openhands.sdk.agent import Agent
from openhands.sdk.conversation import LocalConversation
from openhands.sdk.llm import LLM

from my_extensions.reflection import create_reflexion_critic
from my_extensions.summary_memory import SummaryMemory
from my_extensions.memory_hooks import maybe_compress_history

# 1. 配置 LLM(任意 OpenAI 兼容端点)
llm = LLM(
    model=os.environ["LLM_MODEL"],        # e.g. "openai/glm-4"
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ["LLM_BASE_URL"],  # e.g. "https://open.bigmodel.cn/api/paas/v4"
    max_output_tokens=4096,
)

# 2. 创建带 Reflexion 的 Critic(最多 3 轮迭代,0.7 分才算成功)
critic = create_reflexion_critic(llm=llm, success_threshold=0.7, max_iterations=3)

# 3. 创建 Agent
agent = Agent(llm=llm, tools=[...], critic=critic)

# 4. 创建 SummaryMemory(可以和 Agent 共用同一个 LLM,也可以用便宜的小模型)
summary_memory = SummaryMemory(llm=llm)

# 5. 运行主循环
conversation = LocalConversation(agent=agent, task="帮我写一个 add(a, b) 函数并加单测")
async with conversation:
    async for event in conversation.run():
        # 每轮 tool 调用结束后检查是否需要压缩
        maybe_compress_history(conversation, summary_memory)
        print(event)
```

单独测试各模块:

```bash
python -m my_extensions.reflection      # 测试 ReflexionCritic 实例化和 followup prompt
python -m my_extensions.summary_memory  # 测试 SummaryMemory 基础功能
python -m my_extensions.memory_hooks    # 测试 import 链路
```

---

## 设计哲学 / Design Philosophy

**为什么不 fork 源码?**

1. **维护成本**:fork 后需要跟踪上游每次更新并手动合并,尤其是 SDK 还在快速迭代阶段。
2. **职责边界清晰**:SDK 负责 Agent 主循环、工具调用、事件持久化;扩展只关心"评估质量"和"压缩记忆"两件事,天然解耦。
3. **可移植性**:零侵入意味着这套扩展可以直接用于任何基于 OpenHands V1 SDK 的项目,不需要打补丁。
4. **调试友好**:每个类都可以独立实例化和单测,不依赖完整的 Conversation 上下文。

**provider-agnostic 的实现方式**:所有 LLM 调用通过 `openhands.sdk.llm.LLM` 抽象层,只需传入 `base_url` 即可对接任意 OpenAI 兼容端点——无论是 GLM、Qwen、本地 Ollama 还是 OpenAI 官方 API。

---

## 依赖 / Dependencies

```
openhands-sdk >= 1.0    # 官方 SDK(提供 CriticBase, LLM, EventLog 等)
pydantic >= 2.0         # ReflexionCritic 字段校验
python-dotenv           # 环境变量加载(示例用)
```
