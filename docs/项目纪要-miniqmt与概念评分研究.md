# 项目纪要：miniqmt 研究库 · 概念板块 · 每日评分（研究用）

> 本文档总结仓库内与 **miniqmt 研究 / 板块成分 / 概念选股 CSV 评分** 相关的约定与参数，便于续作与 Code Review。  
> **不含**本机绝对路径、券商名称、资金账号、Token；运行前请在本机自行配置 `MINIQMT_SQLITE_PATH`、`MINIQMT_USERDATA` 等（见 `examples/miniqmt_research/README.md`）。

**更新日期**：2026-05-11（会话整理）

---

## 1. 数据与表

| 资源 | 说明 |
|------|------|
| 默认 SQLite | `examples/miniqmt_research/data/miniqmt.sqlite`（大文件已被 `.gitignore` 忽略，勿提交） |
| `bars` | 日线 `period='1d'` 等，供评分与回测 |
| `sector_member` | 主键 `(sector_name, code)`，一股可多板块 |
| `sector_meta` | 板块元数据 |
| `stock_cn_name` | `code → name`，可由独立脚本或评分脚本内 xtdata 补全 |

板块落库脚本：`examples/miniqmt_research/download_sector_members_to_db.py`（`--include all` 可含名称中无「概念」字样的题材板块）。

---

## 2. 概念解析与「机器人」族

- 客户端展示名与 **xtdata `get_sector_list` 返回的 `sector_name`** 可能不一致（例如带 `TGN` 前缀），属命名差异，非同步失败。
- **`--union-substring`**：按 `sector_name LIKE %子串%` 合并多板块成分并 **去重**，CSV 列 **`matched_sectors`** 记录该股命中板块（分号拼接）。
- 单板块模式仍支持 **`--sector`** + 名称解析（精确匹配优先，再以「后缀匹配 + 名称更短」等规则择一）。

---

## 3. 回测与离线流水线（与 README 对齐）

仓库内与 **回测 / 多周期量价** 相关入口以 `examples/miniqmt_research/README.md` 为准，主要包括：

- **涨停与因子链路**：`limit_up_*` 系列、`limit_up_o2c_backtest.py`、归档脚本等。
- **离线多周期 V1**（仅本地 `bars`，不调 xtdata）：`offline_multi_tf_research/run_pipeline_v1.py`、`backtest_v1.py`、`live_exec_simulator_v1.py`、`auto_iterate_until_85.py` 等。

本纪要不重复各脚本全部 CLI，请 **`python … --help`** 或读该 README。

---

## 4. 概念评分脚本：`concept_sector_screen_csv.py`

### 4.1 输出位置

- 默认目录：`examples/miniqmt_research/daily_picks/`
- 默认文件名：`screen_{union|sector}_…_YYYYMMDD.csv`；同目录 **`latest_screen.csv`** 为最近一次成功结果的快照（写入时用临时文件 + `os.replace`，避免 Excel 占用导致失败；仍失败则生成带时间戳的备用文件）。
- **`--out`** / **`--out-dir`** 可覆盖。

### 4.2 技术面 `score_0_100`（0–100，clip）

与 `pro_live_quant` 一致使用 **`compute_support_resistance`**。分项（代码见 `_score_row`）：

| 项 | 规则摘要 |
|----|-----------|
| 收盘 vs MA20 | 站上 +28；相对 MA20 乖离 `bias*120` 贡献 clip 到 [-8, 18] |
| MA5>MA20 | +12 |
| 量比 | `(vr-1)*15` clip 到 [-5, 22] |
| 5 日涨幅 | [-2%, 12%] 内 +18；>15% 视为偏热 -12 |
| 支撑/压力带 | 在 [sup,res] 区间内位置 `pos*22` clip [0,20]；贴近支撑/压力记入 `score_note` |
| 总分 | 上述求和后 **clip 到 [0,100]** |

默认至少 **`--min-daily-rows`**（默认 60）根日线才参与打分。

### 4.3 买入优先级 `buy_priority` / `priority_score`

在 `score_0_100` 与买卖中文提示基础上计算 **`priority_score`**，再 **降序** 赋 **`buy_priority`=1 最高**（见 `_priority_score_parts` + `_apply_buy_priority_columns`）：

**买点加分（文案子串）**

- 「放量站均线」+15  
- 「贴近支撑位」或「低吸」+12  
- 「支撑上方运行」+6  
- 「信号一般」或「观望」-22  

**卖点扣分**

- 「接近压力位」+8（作为 penalty 从 priority 中减去，下同）  
- 「接近预设止盈」+5  
- 「失守 MA20」+18  

**量比微调**：`min(vol_ratio, 3.5) * 0.35` 加入 `priority_score`。

### 4.4 中文简称

- 先读 `stock_cn_name`；缺省则默认调 **`xtdata.get_instrument_detail`** 补全并写回表（需 miniQMT；`--skip-xt-name-fill` 可关）。  
- **`--name-fill-sleep`** 默认 0.02s 限频。

### 4.5 文本关注池

- `examples/miniqmt_research/daily_picks/picks_report.py`：读带 `buy_priority` 的 CSV，生成 UTF-8 文本列表（研究用）。

### 4.6 自动化流水线（PowerShell）

- `examples/miniqmt_research/data/run_sector_sync_full_auto.ps1`：全量板块落库 + 日志监控 + SQLite 行数校验（**不在脚本内写死** `MINIQMT_USERDATA`；运行前必须在环境中设置）。  
- `examples/miniqmt_research/data/run_robot_sync_and_screen_auto.ps1`：串联板块同步 + 机器人 union 评分 + `picks_report`；输出在 `daily_picks/` 下按日期命名，并维护 `latest_*` 副本名（见脚本内注释）。

---

## 5. 第三方学习资料（MIT）

- 路径：`docs/reference/mattpocock-skills/`（上游 [mattpocock/skills](https://github.com/mattpocock/skills)，MIT License；**已去掉嵌套 `.git`**，作为普通目录纳入本仓库，避免 submodule 空壳。）  
- 索引：`docs/reference/README_mattpocock_skills_学习指引.txt`  
- 与 Cursor Skills 格式理念相近，**非**运行时代码依赖。

---

## 6. 隐私与提交约定

- **勿提交**：本地 `.sqlite`、大 CSV 归档、`runs/`、含账号的 `set_miniqmt_env_local.cmd`、`daily_picks/*.csv`（可复跑生成）。  
- **勿在文档中粘贴**：真实 `userdata_mini` 绝对路径、券商名、账号、API Key。  
- 本纪要仅描述**相对路径与参数逻辑**，便于安全推送至 GitHub。
