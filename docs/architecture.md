# 架构说明

通用的分层问答 Agent 参考架构。数据与场景均为虚构，不对应任何公司系统。

## 总览图

![架构总览](architecture.png)

> 上图由下方的 Mermaid 源码导出（`architecture.png`），颜色按层区分：靛蓝为规划、深色为编排与合成、青色为三条能力臂、灰白为逐级兜底、橙色为守卫、紫色虚线为跨团队异步链路。

```mermaid
flowchart TD
    U([用户问题]) --> P[意图规划 planner<br/>模型给出 plan，代码按白名单校验]
    P -->|模型输出不可用| K[关键词先验 prior<br/>仅兜底，不裁决]
    P --> O[编排 orchestrator]
    K --> O

    O --> L[取数臂 lookup]
    O --> W[词包臂 packs]
    O --> Q[知识问答臂 qa]
    O -.需要专家.-> B[异步桥 bridge]

    L --> L1[L1 确定性查表]
    L1 -->|未命中| L2[L2 有界工具循环<br/>最多 2 轮 / 8 秒 / 数字守卫]
    W --> W0[L0 精确匹配]
    W0 -->|未命中| W1[L1 模型树导航<br/>超时即放弃]
    W1 -->|失败| W2[L2 澄清卡片]
    Q --> R[关键词检索 + 来源名]

    L1 --> C[合成 compose]
    L2 --> C
    W0 --> C
    W1 --> C
    W2 --> C
    R --> C

    C -->|无需专家| G[输出守卫 guard<br/>确定性 / 失败即拒答]
    G --> A([即时回复])

    C -->|草稿| H[草稿暂存 + 截止时间]
    B --> S[外部专家 Agent<br/>慢，由其他团队维护]
    O -->|立刻返回受理回执| A
    S --> F[融合改写 LLM]
    H --> F
    F --> G2[输出守卫 第二遍]
    H -->|专家超时| G2
    G2 --> D([异步投递<br/>fused / draft_timeout / late_update])

    classDef model fill:#eef2ff,stroke:#4f46e5,stroke-width:1.5px,color:#1e1b4b;
    classDef core  fill:#1f2937,stroke:#0f172a,stroke-width:1.5px,color:#ffffff;
    classDef arm   fill:#ecfeff,stroke:#0891b2,stroke-width:1.5px,color:#083344;
    classDef level fill:#ffffff,stroke:#94a3b8,stroke-width:1.2px,color:#334155;
    classDef guard fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#7c2d12;
    classDef draft fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px,color:#713f12;
    classDef ext   fill:#faf5ff,stroke:#a855f7,stroke-width:1.5px,stroke-dasharray:5 3,color:#581c87;
    classDef io    fill:#f8fafc,stroke:#64748b,stroke-width:1.2px,color:#1e293b;

    class U,A,D io;
    class P,K model;
    class O,C core;
    class L,W,Q arm;
    class L1,L2,W0,W1,W2,R level;
    class G,G2 guard;
    class H draft;
    class B,S,F ext;
```

## 组件

| 组件 | 职责 | 用不用模型 | 失败时 |
|---|---|---|---|
| planner | 判断需要哪几类能力 | 是 | 退回关键词先验 |
| lookup L1 | 类目、渠道、目标命中就直接查表 | 否 | 进 L2 |
| lookup L2 | 模型补全未解析的维度，最多 2 轮 | 是 | 列出可选类目 |
| packs L0/L1/L2 | 精确匹配、模型导航、澄清 | L1 用 | 澄清卡片 |
| qa | 关键词检索，返回段落与来源 | 否 | 返回“未找到” |
| bridge | 异步调用外部专家，立即返回回执 | 否 | 草稿到期后发出 |
| delivery | 暂存草稿、融合、去重、超时兜底 | 融合用 | 发草稿 |
| guard | 删除敏感列、名单表、敏感句，再校验 | 否 | 返回拒答文案 |

## 请求流程

**同步路径**：规划 → 运行各臂 → 合成 → 守卫 → 返回。

**异步路径**（plan 含 external）：规划 → 运行本地臂 → 合成本地草稿 → 提交专家并立即返回回执
（含 ref）→ 专家答复到达后，草稿与答复融合成一条 → 守卫 → 投递。专家超时则发送草稿。
同一个 ref 只会发送一次；专家在草稿发出后才到达，则作为 `late_update` 单独发送。

## 可观测

每次回复带 `trace`：plan 与来源（llm / prior）、各臂的层级（L0/L1/L2）与耗时、守卫命中项。
