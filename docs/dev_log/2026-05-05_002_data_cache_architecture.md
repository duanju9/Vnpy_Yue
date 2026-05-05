# 数据架构设计：缓存层（候选 A）+ 后续「指数对比 / 形态筛选 / 板块相似度」

- 日期：2026-05-05（北京时间）
- 范围：
  - 新增包 ``vnpy/feeds/``（``tsy_pro``、``daily_store``、``registry``、``cached_daily``、``paths``）
  - ``examples/tsy_xiaodefa_client.py`` 改为复用 ``vnpy.feeds``
  - ``examples/quick_tests/dual_ma_smoketest.py`` 增加 ``--use-cache``；修复 ``trade_date`` 解析（``.str[:8]``，勿用 ``Series[:8]``）
  - ``examples/quick_tests/cache_smoke.py`` 缓存命中对比
  - ``pyproject.toml`` 增加可选依赖组 ``[feeds]``
  - ``.gitignore`` 增加 ``data/vnpy_yue/``
- 触发动机：用户选择先做候选 A（数据缓存层），并规划后续统计需求：
  - 最近指数涨多少、某周期内哪些股票跑赢指数与大盘
  - 某时间段内符合某形态的标的跟踪与分类
  - 板块相似度、跟踪板块聚合分析

---

## 一、设计目标（分层）

| 层级 | 职责 | 本期实现 | 下一迭代 |
|------|------|----------|----------|
| **L0 原始拉取** | 小龙虾 / 官方 Tushare 限速、改地址 | ``vnpy.feeds.get_pro_throttled`` | 重试退避、熔断 |
| **L1 本地 Bronze** | 按标的落盘原始日线，可重复合并 | ``data/vnpy_yue/daily/*.parquet`` | 分钟线子目录 ``minute/`` |
| **L2 元数据** | 缓存覆盖区间、同步流水、便于审计 | ``manifest.sqlite``（``symbol_daily_meta``、``sync_run``） | 指数成分、行业映射表 |
| **L3 分析 Silver** | 截面收益、相对指数超额、窗口聚合 | **推荐 DuckDB** 读 Parquet | 或 Polars 批扫 |
| **L4 标签 Gold** | 形态命中、策略信号、板块 embedding | 新表 ``pattern_hit``、``sector_embedding`` | 与 ``vnpy.alpha`` 对齐 |

原则：**热路径写 Parquet（列式、压缩好）**；**元数据与关系、审计用 SQLite**；**重型截面/多表 JOIN 用 DuckDB 单文件**；**实盘 Tick/高频录制继续用 VeighNa 官方 TDengine/SQLite 录制栈**。

---

## 二、本期落地：目录与 API

### 1) 数据根目录

- 默认：``<仓库根>/data/vnpy_yue/``
- 覆盖：环境变量 ``VNPY_YUE_DATA=/path/to/dir``

### 2) 文件布局

```
data/vnpy_yue/
├── manifest.sqlite          # SQLite：元数据 + sync_run
└── daily/
    ├── 002709_SZ.parquet    # 单标的全历史（合并增长）
    └── 600519_SH.parquet
```

### 3) 公开 API（``from vnpy.feeds import …``）

- ``get_pro_throttled()`` — 小龙虾限速 + 改 HTTP 地址
- ``fetch_daily_cached(ts_code, start, end, force_refresh=False)`` — 若本地已覆盖 ``[start,end]`` 则**不打接口**；否则 ``daily`` 一次拉整段后 ``merge_and_write``
- ``DailyBarStore`` / ``FeedRegistry`` — 扩展自定义流水线时使用

### 4) 依赖

安装：

```bash
pip install -e ".[feeds]"
```

或手动：``tushare python-dotenv pyarrow``。

---

## 三、数据库选型（回答「用什么库合适」）

### 1) 本地投研默认组合（推荐）

| 组件 | 适用场景 | 理由 |
|------|----------|------|
| **Apache Parquet** | 全市场日线/分钟 OHLCV 主存储 | 列存、压缩比高、与 Pandas/Polars/DuckDB 零拷贝衔接；按 ``ts_code`` 单文件便于增量合并 |
| **SQLite** | 元数据、同步流水、成分股、行业、形态命中索引 | 单文件、无运维、事务可靠；适合「注册表」类数据 |
| **DuckDB**（建议下一 PR） | 「某窗口谁跑赢沪深300」「全市场截面相关矩阵」「板块收益率序列 JOIN」 | 直接 ``read_parquet('daily/*.parquet')`` + SQL；单机 OLAP 极强，安装轻 |

三者关系：**Parquet 是事实表；SQLite 是目录与标签索引；DuckDB 是分析引擎**（也可只用 Polars 替代 DuckDB，团队更熟 Python 时选 Polars）。

### 2) 与官方 vnpy 生态的关系

- **TDengine / MongoDB / PostgreSQL**：适合 **实时录制 Tick、多策略共享行情**（``vnpy_datarecorder``、生产环境）。本仓库的 **投研缓存** 不必一上来就上时序库，避免运维成本。
- **vnpy.alpha + Polars**：因子矩阵、机器学习管线已在 4.x 路线图中；**L3 可把 DuckDB 查询结果导出为 Polars DataFrame** 再进 ``AlphaDataset``。

### 3) 不推荐单独用「纯 SQLite 存全市场 K 线」

- 行存 + 大表 B-tree，全市场多年日线体积与查询性能不如 Parquet + DuckDB。
- SQLite 更适合：**成分变更、板块树、形态标签、任务队列**。

---

## 四、后续需求映射到表/文件（实现草图）

### 1) 「最近指数涨多少」「某周期谁跑赢指数」

- **数据**：指数日线同样走 ``fetch_daily_cached('000001.SH', …)`` 或对应指数代码；股票池批量循环（仍受 120 次/分钟约束，需**任务队列 + 夜间批跑**）。
- **计算**（DuckDB 伪 SQL）：

```sql
-- 个股与指数对齐交易日，算窗口收益与超额
WITH r AS (
  SELECT ts_code, trade_date,
         close / LAG(close) OVER (PARTITION BY ts_code ORDER BY trade_date) - 1 AS ret
  FROM read_parquet('data/vnpy_yue/daily/*.parquet')
)
SELECT s.ts_code,
       EXP(SUM(LN(1 + s.ret))) - 1 AS stock_window_ret,
       EXP(SUM(LN(1 + idx.ret))) - 1 AS index_window_ret
FROM r s
JOIN (SELECT trade_date, ret FROM r WHERE ts_code = '000001.SH') idx
  USING (trade_date)
WHERE s.trade_date BETWEEN '20260101' AND '20260331'
GROUP BY s.ts_code;
```

- **落地**：新增 ``scripts/build_duckdb_research.py`` 或 ``vnpy/feeds/duckdb_views.py``（下一篇 dev_log）。

### 2) 「某时间段符合形态的跟踪 / 股票分类」

- **存储**：SQLite 表 ``pattern_hit(id, ts_code, pattern_id, t_start, t_end, score, payload_json)``；或 Parquet 分区 ``labels/pattern_id=chan_bi_break/…``。
- **流水线**：形态检测（如后续 ``chan.py``）输出事件行 → 写入 SQLite → DuckDB 与日线 JOIN 做回测。

### 3) 「板块相似度」

- **输入**：板块日收益序列（可由东财/同花顺板块指数接口写入 ``daily/`` 或单独 ``sector_daily/``）。
- **相似度**：
  - 简单：滚动 60 日收益序列的 **Pearson 相关**（DuckDB / numpy）
  - 进阶：图聚类（相关矩阵 → Louvain）或 **embedding**（后续可接小模型，非本期）

建议在 SQLite 增加 ``sector_meta(sector_code, name, …)``，Parquet 存 ``sector_code`` 日线。

---

## 五、验证命令（可复现）

```powershell
cd d:\Vnpy\Vnpy_Yue
pip install -e ".[feeds]"   # 若尚未安装 pyarrow

# 缓存命中对比
python examples/quick_tests/cache_smoke.py

# 双均线 + 缓存（第二次同参数应极快）
python examples/quick_tests/dual_ma_smoketest.py --ts_code 002709.SZ --short 10 --long 30 --start_date 20240101 --use-cache
python examples/quick_tests/dual_ma_smoketest.py --ts_code 002709.SZ --short 10 --long 30 --start_date 20240101 --use-cache

# 兼容旧入口
python examples/tsy_xiaodefa_client.py
```

**预期**：``cache_smoke`` 第二次耗时显著低于第一次；``manifest.sqlite`` 中 ``sync_run`` 在第二次同区间不应新增行（因命中缓存、不请求网络）。

**附**：``dual_ma_smoketest`` 在接入缓存后曾误用 ``Series[:8]``（取前 8 **行**）解析日期，已改为 ``.str[:8]`` 取前 8 **字符**，避免末行 ``NaT``。

---

## 六、安全与合规

- ``data/vnpy_yue/`` 已加入 ``.gitignore``，勿提交 Parquet/SQLite。
- Token 仍只放 ``.env``，代码中不出现明文。

---

## 七、下一篇 dev_log 建议标题

- ``2026-05-0X_003_duckdb_research_views.md``：引入 DuckDB 单文件 ``research.duckdb`` + 预置「窗口收益 / 相对指数超额」视图/SQL 模板。
