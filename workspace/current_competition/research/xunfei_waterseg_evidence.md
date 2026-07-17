# 水体分割研究证据与复现排序

检索日期：2026-07-16。自动雷达的原始结果在 `research/papers.json`；本文件只保留经人工相关性审查后能影响本赛题决策的证据。

## 结论

隐藏测试按地点隔离时，跨地域泛化比继续堆叠 decoder 模块更值得优先验证。但论文结果不能直接迁移为比赛收益；每个候选必须先在同一 fold、相同训练预算下超过当前 v15 历史记录，才允许扩大训练预算。

## 证据卡

### P0 - 先复现本地 v16：数据采样和 OHEM

- 证据：已有工程的 v16 实现已经把 768 crop 分为 positive / negative / uniform，并使用 OHEM-BCE、Lovasz、Dice 和边界辅助；这正对齐本地 1.58% 前景比例与阴影/暗道路假阳性风险。
- 状态：**可执行**，受 `waterseg_external` 源码指纹、规则确认和精确 GPU 审批保护。
- 晋级门槛：fold-0 768→1024 完整流程的无 TTA IoU，须在同一 split/seed 比 v15 对照高至少 0.003，并检查 precision、recall、P10 图像 IoU 与 boundary F1。

### P1 - Fourier amplitude mix：低成本域泛化消融

- 论文：Xu et al., CVPR 2021。该工作用频域幅度混合和一致性约束处理未见域分布偏移。
- 对本赛题的推断：可作为 RGB 外观/季节变化的轻量增广；不是遥感水体专用结论，必须只在 v16 稳定复现后单变量消融。
- 状态：**待实现**；不需要额外预训练权重或外部数据。
- 论文：<https://openaccess.thecvf.com/content/CVPR2021/html/Xu_A_Fourier-Based_Framework_for_Domain_Generalization_CVPR_2021_paper.html>

### P2 - Rein：冻结基础模型的参数高效适配

- 论文：Wei et al., CVPR 2024。该工作针对域泛化语义分割，以很少可训练参数对视觉基础模型进行适配。
- 代码：<https://github.com/w1oves/Rein>，仓库为 GPL-3.0，且依赖 mmsegmentation / Mask2Former / DINOv2。
- 对本赛题的推断：适合做“冻结 probe 优于 mit-b4 吗”的受限候选，而不是直接替换现有提交模型。
- 状态：**需独立复现目录**；不得复制或混入 Competition Agent 主源码，且必须先确认预训练权重与许可证在赛题中允许。

### P3 - CrossEarth：遥感跨域语义分割基础模型

- 论文：Gong et al., arXiv 2024 / TPAMI 2025，目标正是遥感跨区域、光谱和平台变化下的语义分割。
- 代码：<https://github.com/VisionXLab/CrossEarth>，MIT 许可证。
- 现实限制：官方仓库写明训练步骤仍为“Coming soon”；不能把它标为可立即完整复现的模型。
- 状态：**研究参考**，只允许在发布了可复现实训入口、并获预训练规则确认后进入 probe。

## 自动检索健康度

- 查询：`remote sensing semantic segmentation domain generalization`。
- arXiv 与 GitHub 成功返回相关记录；OpenAlex 返回 HTTP 503，Semantic Scholar 返回 HTTP 429。
- 自动检索器已修复为显式 arXiv 布尔字段查询，并丢弃标题/摘要不含至少两个查询术语的结果，避免“按日期返回的无关论文”污染候选列表。

## 未经批准不得执行的事项

1. 下载或使用新的基础模型权重；
2. 克隆并运行 Rein 或 CrossEarth；
3. 使用额外遥感数据、伪标签或在线测试反馈参与训练；
4. 导出或上传推理包。

这些不是研究限制，而是把竞赛规则、开源许可证和可复现性同时纳入训练决策。
