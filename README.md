# OpenHands V1 SDK Reflexion 扩展

基于 [OpenHands V1 SDK](https://github.com/OpenHands/software-agent-sdk)的非侵入式扩展,实现 Reflexion 论文的 verbal reinforcement learning 机制。

## 核心特性

- **非侵入扩展**:不修改 OpenHands SDK 源码,所有代码物理隔离于 `my_extensions/`
- **Provider-agnostic**:任意 OpenAI 兼容 LLM 可用(GLM / GPT / Claude),不需要 All-Hands 商业 vLLM 服务
- **Reflexion 范式**:覆写 `get_followup_prompt` 显式注入 issues + lessons,实现 verbal reinforcement learning
- **SummaryMemory**:长任务上下文压缩,基于 SDK 原生 `agent_state` 持久化

## 与官方 APIBasedCritic 的对比

详见 [docs/comparison.md](docs/comparison.md)

简表:

| 维度 | 官方 APIBasedCritic | 本项目 ReflexionCritic |
|---|---|---|
| 评估方式 | 调用 All-Hands 商业 vLLM 服务 | 通用 LLM completion |
| 依赖 | 必须接入 All-Hands LLM Proxy | 任意 OpenAI 兼容 LLM |
| Followup prompt | 父类默认通用模板 | 注入 issues + lessons (Reflexion 范式) |

## 安装与使用

### 前置要求

```bash
# 1. 克隆官方 SDK
git clone https://github.com/OpenHands/software-agent-sdk
cd software-agent-sdk
uv sync --dev

# 2. 把本项目 my_extensions 放进去
cp -r /path/to/this-repo/my_extensions ./
cp /path/to/this-repo/examples/agent_with_reflection.py examples/
```

### 配置 .env

```env
LLM_MODEL=openai/glm-5.1
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
```

### 运行

```bash
uv run python examples/agent_with_reflection.py
```

## 设计哲学

核心思想:
1. **不要 fork 修改 SDK 源码**——官方提供了 `CriticBase` 抽象基类、`Hooks` 系统、`agent_state` 字段三个扩展点,优雅地用它们
2. **承认官方有 Critic**(`APIBasedCritic`),但聚焦差异化价值:provider-agnostic + Reflexion 范式
3. **每个 Critic 实现服务于具体场景**——`APIBasedCritic` 服务 All-Hands 生态,`ReflexionCritic` 服务自建 / 国产模型

## 真实运行 Demo

[demos/reflection_real_run.log](demos/reflection_real_run.log) - Critic 评估 + Reflexion 触发的真实运行日志。

## 工程踩坑

- **GLM-5.1 思考模型 max_tokens 双重语义**:必须设 4096+,否则思考阶段就被截断,LLM 返空字符串
- **SDK 类型严格性**:`LLM.completion()` 接收的是原生 `Message + TextContent` 对象,传 dict 会报 `'dict' object has no attribute 'to_chat_dict'`
- **过宽容 fallback 反模式**:Critic 失败时静默返回 0.5 score 会触发"虚假反思循环",必须显眼日志 + 报警

## 📊 Benchmark 报告

### 实验设计
- **目的**:量化 ReflexionCritic 在 OpenHands V1 SDK 上的真实价值与成本
- **任务**:7 个 coding 任务(从 easy 到 hard,包含精心设计的 silent failure / edge case trap)
- **LLM**:GLM-5.1(智谱,强制思考模型)
- **配置**:`success_threshold=0.7`, `max_iterations=3`
- **验证方式**:每任务定义 `verify_command`,跑真实命令验证 Agent 输出

### 核心结果

| 指标 | Baseline | With Reflexion | Delta |
|---|---|---|---|
| Pass@1 | 100% | 100% | +0 pp |
| 平均耗时 | 21.1s | 36.2s | **+72%** |
| 平均 Token | 23,070 | 27,959 | **+21%** |

### 关键发现

1. **GLM-5.1 思考模型边际收益结构性偏低**:模型内部 reasoning 阶段已隐含 self-reflection,外部 Reflexion 在简单任务上无显著提升
2. **Reflexion 不是免费午餐**:即使不触发迭代,Critic 评估仍带来 +21% Token 成本
3. **自适应策略建议**:生产环境应根据任务复杂度有条件启用,而非默认全开

完整报告详见 [`benchmark/REPORT.md`](benchmark/REPORT.md)。

### 实验复现

```bash
# 跑单任务
uv run python -m benchmark.runner --task task_h1 --mode with_reflexion

# 批量跑所有任务
uv run python -m benchmark.run_all

# 生成对比报告
uv run python -m benchmark.analyze
```

## License

MIT
