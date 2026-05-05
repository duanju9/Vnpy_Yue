# 开发更新日志（dev_log）

本目录专门记录 **Vnpy_Yue 在官方 vnpy 之外的所有改造痕迹**，为「AI 自动化研究 / 交易引擎」的迭代留档，便于：

- 自查每次改动的目的、范围、验证结果
- 追溯任何一行新代码的「为什么这么写」
- 后续整理论坛文章 / 开源 README 时直接复用素材

## 命名规范

```
docs/dev_log/YYYY-MM-DD_NNN_<slug>.md
```

- `YYYY-MM-DD` — 改动落地当天日期（北京时间）
- `NNN` — 当天的序号，001 起递增
- `<slug>` — 英文小写短描述，如 `dual_ma_smoketest`、`chan_adapter`、`feeds_layer`

## 每篇必填字段

```markdown
# 标题（一句话总结这次改动）

- 日期：YYYY-MM-DD HH:mm（北京时间）
- 范围：本次改了哪些目录 / 文件
- 关联：对应的 git commit / branch / issue（若有）
- 触发动机：为什么要做（用户原话或一句精炼）

## 一、做了什么
（按文件列表，写每个文件的关键改动）

## 二、怎么验证（可复现命令）
（命令、输入、输出截图、关键指标）

## 三、未决事项 / 下一步
（明确列下一篇 dev_log 要完成的事）
```

## 注意事项

- **绝不在 dev_log 里贴任何 token / 密钥**。所有密钥都走 `examples/.env`（已在 `.gitignore`）。
- 涉及回测指标时，附带 commit hash + 数据时间窗，保证可复现。
- 涉及第三方接口（小龙虾 / QMT / 同花顺）时，记录手册链接 + 当时限速 / 配额状态，避免后人踩坑。

## 近期条目索引

| 日期 | 文件 | 摘要 |
|------|------|------|
| 2026-05-05 | [2026-05-05_002_data_cache_architecture.md](2026-05-05_002_data_cache_architecture.md) | 数据缓存层（Parquet + manifest）与后续分析方向 |
| 2026-05-05 | [2026-05-05_003_github_push_session.md](2026-05-05_003_github_push_session.md) | GitHub `master` 推送、`85ee97f` 范围、README_ENG 恢复说明 |
