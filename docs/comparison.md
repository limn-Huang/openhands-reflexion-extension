# ReflexionCritic vs APIBasedCritic 精准对比

> 本文件回答面试常见追问:"OpenHands 不是有 Critic 实现吗,你做的有什么独特?"

## 1. 维度对比表

| 维度 | 官方 APIBasedCritic | 本项目 ReflexionCritic |
|---|---|---|
| **评估方式** | HTTP 调用 All-Hands 部署的 vLLM 服务 | 直接调用 LLM.completion() |
| **依赖** | 必须接入 All-Hands LLM Proxy | 任意 OpenAI 兼容 LLM |
| **模型类型** | 专门训练的 critic 模型 | 通用 LLM(GLM / GPT / Claude) |
| **followup prompt** | 父类默认模板(通用) | 覆写注入 issues + lessons(Reflexion 范式) |
| **输出结构** | 仅 score | score + message + issues + lessons |
| **使用门槛** | 需 All-Hands 商业服务 | 开箱即用 |
| **范式归属** | 不属于学术 paper 范式 | 严格遵循 Reflexion (Shinn et al., 2023) |

## 2. 实现差异的关键代码段

### 官方 APIBasedCritic.evaluate()(伪代码)
```python
def evaluate(self, events, git_patch):
    # 调用远程 HTTP API
    response = requests.post(
        f"{self.server_url}/score",
        json={"events": serialize(events), "patch": git_patch},
        headers={"Authorization": f"Bearer {self.api_key}"}
    )
    return CriticResult(score=response.json()["score"])
```

### 本项目 ReflexionCritic.evaluate()
```python
def evaluate(self, events, git_patch):
    # 用通用 LLM 做 structured self-evaluation
    response = self.llm.completion(messages=[
        Message(role="system", content=[TextContent(text=REFLECTION_CRITIC_SYSTEM)]),
        Message(role="user", content=[TextContent(text=user_prompt)]),
    ])
    # 解析结构化输出:score + issues + lessons
    return parse_critic_result(response.message.content)
```

**核心差异**:官方调远程专用服务,本项目用通用 LLM + structured prompt 实现 self-evaluation。

## 3. 适用场景

| 场景 | 推荐 |
|---|---|
| 接入 All-Hands 商业生态 | APIBasedCritic |
| 自建 Agent 服务 / 国产 LLM | ReflexionCritic |
| 追求 Reflexion 论文复现 | ReflexionCritic |
| 不想自己写 prompt | APIBasedCritic(自动用专用模型) |

## 4. 我做这个的工程理由

1. **provider 锁定问题**:APIBasedCritic 等于绑定 All-Hands 生态,我希望任何 LLM 都能用
2. **论文范式落地**:Reflexion 的 verbal reinforcement 思想要求显式注入 issues/lessons,APIBasedCritic 没做这件事
3. **可观测性**:我的 Critic 输出 lessons,后续可沉淀到长期 memory(SummaryMemory),官方版只有 score 不可复用

## 5. 已知局限

诚实标注,避免面试翻车:

- ❌ 没有专门训练的 critic 模型,评估质量依赖 base LLM 的指令遵循能力
- ❌ 通用 LLM 调用比专用 critic 模型慢 2-5x(因为要做 prompt engineering)
- ❌ JSON 输出有时被 markdown 包裹,需要 robust parsing(项目里已处理)