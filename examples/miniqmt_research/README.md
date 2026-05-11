# miniqmt 研究库（K 线落库 + 涨停研究）

全市场 A 股 **5m / 60m / 1d** 落入本地库 **miniqmt**（SQLite 默认在 `data/miniqmt.sqlite`），带断点与限频；同目录脚本可做 **涨停事件、次日溢价回测、研究留档**。

在仓库根目录 **`Vnpy_Yue`** 下执行下文命令。

---

## 醒目：涨停前独立脚本 与 归档开关

| 用途 | 命令 |
| --- | --- |
| **只跑「涨停前一日 → 次日涨停」命中率分层**（结果写入 `output/limit_up/`，不生成 `runs/` 子目录） | `python examples/miniqmt_research/limit_up_pre_limit_study.py --train-end 2025-12-31` |
| **完整研究留档**（含 **`实盘策略规格.md`**、审慎说明 / **`go_live_assessment.json`**、**`strategy_research_score.json`**（0–100 研究综合分+等级，**非**实盘许可）、按年/**按季/按月** **`产物/calm_t3_stop_by_*.csv`**；默认附带涨停前 `pre_limit_*` 与 `metrics.json`） | `python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor` |
| **留档但跳过涨停前**（加快跑批、减小产物；**不传则默认要跑涨停前**） | `python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor --no-pre-limit` |
| **离线多周期量价流水线 V1**（仅读本地 `bars` 的 5m/60m/1d：数据校验→因子→回测→打分→留档，**不调用 xtdata**） | `python examples/miniqmt_research/offline_multi_tf_research/run_pipeline_v1.py --sqlite examples/miniqmt_research/data/miniqmt.sqlite` |
| **V1 实盘执行模拟（5m 按 bar 触价出场 vs 日线回测对照，不改 `backtest_v1`）** | `python examples/miniqmt_research/offline_multi_tf_research/live_exec_simulator_v1.py --sqlite examples/miniqmt_research/data/miniqmt.sqlite` |
| **多轮迭代至目标分（脚本无人值守）** | `python examples/miniqmt_research/offline_multi_tf_research/auto_iterate_until_85.py`（环境变量 `MAX_ITERATIONS`、`SCORE_TARGET`） |
| **板块行业/概念成分落库**（`sector_meta` / `sector_member`，供概念选股） | `python examples/miniqmt_research/download_sector_members_to_db.py --include concept,industry`（需 miniQMT + xtdata） |
| **证券中文简称落库**（表 `stock_cn_name`：code→name） | `python examples/miniqmt_research/download_stock_cn_names_to_db.py`（默认从 `sector_member` 去重 code；`--max-codes` 试跑；需 `MINIQMT_USERDATA`） |

其它常用参数：`--sqlite`、`--events-dir`、`--train-end`、calm 区间 `--td-min` `--td-max` `--v5-min` `--v5-max`；见各脚本 `python ... --help`。

**Excel 中文字段留档**：归档会生成 `产物/研究报告留档.xlsx`，需安装 `openpyxl`：

`pip install -r examples/miniqmt_research/requirements-research.txt`

---

## 1. 新建 PostgreSQL 库（可选）

若使用 PostgreSQL，库名建议为 `miniqmt`：

```bash
createdb miniqmt
# 或 psql: CREATE DATABASE miniqmt;
```

安装驱动：`pip install 'psycopg[binary]>=3.1'`

```bash
set MINIQMT_PG_URI=postgresql://用户:密码@127.0.0.1:5432/miniqmt
```

不设 `MINIQMT_PG_URI` 时，默认 **SQLite**：`examples/miniqmt_research/data/miniqmt.sqlite`（可用环境变量 `MINIQMT_SQLITE_PATH` 或下载脚本参数 `--sqlite` 覆盖）。

## 2. 运行前

- 启动 **miniQMT**，本机 Python 能 `from xtquant import xtdata`。
- 建议设置 `MINIQMT_USERDATA` 指向 `userdata_mini`。

## 3. 下载 K 线

**每日自动更新本地库（Windows）**：可用任务计划程序调用  
`examples/miniqmt_research/scripts/daily_bars_update.ps1`（内需已安装 Python，且 miniQMT/xtdata 环境仍用于**下载**步骤）。

```bash
python examples/miniqmt_research/download_bars_to_db.py --dry-run
python examples/miniqmt_research/download_bars_to_db.py --max-stocks 5
# Windows PowerShell：周期里的 1d 建议加引号
python examples/miniqmt_research/download_bars_to_db.py --sleep 0.25 --periods "1d,60m,5m"
```

全市场 + 长区间 + 多周期请求量很大，请从小样本试跑；中断后重跑会跳过已 `ok` 的 `(code, period)`。`--force` 可强制重拉。

## 4. 表结构（摘要）

- `bars`：`period`, `code`, `ts`, `open`, `high`, `low`, `close`, `volume`, `amount`
- `dl_job`：每 `(code, period)` 的下载状态与时间范围

## 5. 涨停因子、回测与留档

在已有 `data/miniqmt.sqlite` 与 `output/limit_up/limit_up_events.csv` 前提下（事件表由第一步生成）：

```bash
python examples/miniqmt_research/limit_up_factor_mining.py
python examples/miniqmt_research/limit_up_analyze.py
python examples/miniqmt_research/limit_up_o2c_backtest.py
```

产物含 `output/limit_up/` 下的 `analysis_report.md`、`strategy_o2c_report.md`、`strategy_o2c_trades.csv` 等。

**每次研究留档**（生成 `runs/<tag>_YYYYMMDD_HHMMSS/`，含 `说明与结论.md`、`选股说明.md`、`实盘策略规格.md`、`分发说明.md`、`manifest.json`（全文件清单）、`metrics.json`、`跑批记录.md`、`产物/`；检验含 **按年/按季** CSV 与 Excel 表）：

```bash
python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor
python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor --td-min 5 --td-max 40 --v5-min 1.0 --v5-max 2.2
python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor --capital-cny 10000
python examples/miniqmt_research/limit_up_research_archive.py --tag limit_up_factor --no-pre-limit
```

**再次说明**：`--no-pre-limit` 仅作用于 **`limit_up_research_archive.py`**，用于关闭归档里的涨停前命中率块；**`limit_up_pre_limit_study.py` 不受影响**，需单独运行。

**展示用本金**：`--capital-cny`（默认 **10000**）写入 `metrics.json` 的 `capital_illustrative_cny`、`产物/研究报告留档.xlsx` 的金额列及《实盘策略规格》§4.3 / §5；为研究换算口径，**非**强制满仓指令。

## 6. 子目录说明

- `data/`：默认 SQLite 位置，见 `data/README.txt`（大文件勿提交 git）。
- `runs/`：归档输出，见 `runs/README.txt`（勿提交大 CSV）。
- `daily_picks/`：概念/板块评分 CSV 默认输出（`*.csv` 已 `.gitignore`，见仓库根说明）。

## 7. 概念板块评分与项目纪要

- 脚本：`concept_sector_screen_csv.py`（默认写入 `daily_picks/`，含 `score_0_100`、`buy_priority`、xtdata 补中文名等）。
- **参数与回测入口汇总**（无隐私路径）：仓库根 `docs/项目纪要-miniqmt与概念评分研究.md`。
