# 源码快照说明

本目录为 **与仓库 `examples/quick_tests/` 同步拷贝的 Python 源码**，便于将「策略热股5分钟-20260424_20260507」文件夹 **单独打 zip** 时，收件人仍能查看实现细节。

## 如何运行回测（推荐）

不要直接运行本目录下的 `qmt_batch_hot_rank_backtest.py`（其内部 `_REPO` 仍按「脚本位于 `quick_tests/`」解析，路径会错位）。

请在本包 **上一级仓库根目录 `Vnpy_Yue`** 下执行包内启动器：

```text
python examples/quick_tests/策略热股5分钟-20260424_20260507/本包回测_THS三连跑.py
```

Excel 会写入本包 **`产物/`** 目录，文件名带 **`策略热股5m交付_THS20260424-0707_`** 前缀。

## 文件列表

| 文件 | 说明 |
|------|------|
| `qmt_5m_vol_pullback_macd_backtest.py` | 5m 规则引擎 + 单标的 / 批量汇总列 |
| `qmt_batch_hot_rank_backtest.py` | 人气批量入口 |
| `backtest_recorder.py` | JSONL 追加记录（写入仓库 `output/backtest_runs.jsonl`） |

拷贝日期以你本机文件为准；与主分支有差异时 **以仓库内未拷贝文件为准**。
