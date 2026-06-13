# ReflexionCritic Benchmark Report

_生成时间: 2026-06-13 21:36:55_

## 实验设计

- **目的**: 对比 OpenHands V1 SDK 在 baseline 模式与启用 ReflexionCritic 模式下的任务完成质量
- **任务**: 5 个 coding 任务(从 easy 到 hard,涵盖 edge case 与多文件)
- **LLM**: GLM-5.1
- **Reflexion 配置**: success_threshold=0.7, max_iterations=3
- **验证方式**: 每个任务定义 `verify_command`,跑真实命令检查输出

## 实验对比:Baseline vs With Reflexion

| Task | Difficulty | Baseline 成功 | Reflexion 成功 | Baseline 时间 | Reflexion 时间 | Reflexion 迭代次数 | Baseline Token | Reflexion Token | Token 增量 |
|------|-----------|------------|---------------|-------------|----------------|------------------|----------------|------------------|------------|
| task_1 | easy | ✅ | ✅ | 9.1s | 15.1s | 0 | 16,995 | 21,046 | +23.8% |
| task_2 | easy | ✅ | ✅ | 15.3s | 28.8s | 0 | 17,667 | 22,362 | +26.6% |
| task_4 | medium | ✅ | ✅ | 23.3s | 35.6s | 0 | 31,913 | 37,306 | +16.9% |
| task_5 | hard | ✅ | ✅ | 20.3s | 38.4s | 0 | 18,927 | 24,278 | +28.3% |
| task_h1 | hard | ✅ | ✅ | 31.0s | 44.5s | 0 | 24,574 | 29,452 | +19.9% |
| task_h2 | hard | ✅ | ✅ | 21.5s | 44.5s | 0 | 19,770 | 25,048 | +26.7% |
| task_h3 | hard | ✅ | ✅ | 27.0s | 46.5s | 0 | 31,641 | 36,221 | +14.5% |

## 总体统计

| 指标 | Baseline | With Reflexion | Delta |
|------|----------|----------------|-------|
| 实验次数 | 7 | 7 | - |
| Pass@1 (任务通过率) | 100.0% | 100.0% | **+0.0 pp** |
| 平均耗时 | 21.1s | 36.2s | +71.6% |
| 平均 Token | 23,070 | 27,959 | +21.2% |
| 平均 Action 数 | 4.3 | 4.3 | - |

## Reflexion 触发详情

| Task | Critic Scores | 触发 Reflexion | 迭代次数 | 最终结果 |
|------|---------------|---------------|----------|----------|
| task_1 | 1.00 | ❌ | 0 | ✅ |
| task_2 | 0.85 | ❌ | 0 | ✅ |
| task_4 | 0.94 | ❌ | 0 | ✅ |
| task_5 | 1.00 | ❌ | 0 | ✅ |
| task_h1 | 1.00 | ❌ | 0 | ✅ |
| task_h2 | — | ❌ | 0 | ✅ |
| task_h3 | 1.00 | ❌ | 0 | ✅ |

## 关键洞察

### 1. Reflexion 在 GLM-5.1 思考模型上边际收益接近零

本次实验覆盖 7 个不同难度的 coding 任务(easy / medium / hard),包括精心设计的 3 个 'silent failure' / 'edge case trap' 任务。结果:

- Baseline Pass@1: **100%**(7/7 全部通过)
- Reflexion Pass@1: **100%**(无任何额外提升)
- Reflexion 在所有任务上**均未触发迭代**(Critic 给出 0.85~1.00 高分)

**根因分析**:GLM-5.1 是强制思考模型(Forced-Thinking Model),其内部 reasoning 阶段已经隐含了 self-reflection 过程。外部 Reflexion 在这类'已具备内嵌反思能力'的模型上,边际收益结构性偏低。

### 2. Reflexion 的真实成本可量化

即使任务一次过,启用 Critic 仍会产生固定开销:

- 平均耗时:**+71.6%**(Critic 评估 LLM 调用)
- 平均 Token:**+21.2%**(Critic prompt + 评估输出)
- 平均 Action 数:几乎不变(4.3 → 4.3,因为 Reflexion 未触发)

**结论**:**Reflexion 不是免费午餐**,在简单任务上是纯负担。

### 3. 工程建议:自适应 Reflexion 策略

基于实验数据,推荐生产环境采用 **conditional Reflexion**:

- **简单任务**(初步可判定为 well-defined / 单文件):跳过 Critic
- **复杂任务 / 关键路径**(多文件 / 涉及核心业务逻辑):启用 Reflexion
- **失败重试场景**(任务 explicit 报错 / verify 不通过):必须启用 Reflexion

这是用 +21% Token 成本换取容错能力的**有条件保险机制**,而非对所有任务一刀切的 cost-quality 权衡。

### 4. 关于实验边界的诚实声明

本实验仅覆盖 GLM-5.1 + 7 个 coding 任务的 baseline 对比。Reflexion 在以下场景的价值尚未验证:

- 非思考模型(如 GPT-3.5、GLM-4-Flash)上的提升幅度
- 长任务(>20 actions)的累积错误纠正
- Tool-use 链路(数据库 / API)中的失败恢复

未来工作可扩展到这些场景,以建立完整的 Reflexion 适用边界图。
