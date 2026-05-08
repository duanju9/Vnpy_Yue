# 将 miniQMT（xtdata）接入 chan.py（推荐路径）

本目录下的 `XtQuant.py` **不是**给 Vnpy_Yue 直接 `import` 用的，请**复制到 chan.py 仓库**里使用。

## 步骤

1. 克隆 [chan.py](https://github.com/Vespa314/chan.py)，使用 **Python 3.11+** 虚拟环境并安装其依赖。  
2. 把本目录的 **`XtQuant.py`** 复制到 chan 仓库的 **`DataAPI/XtQuant.py`**（与 `BaoStockAPI.py` 同级）。  
3. 启动 **miniQMT / QMT**；可选设置环境变量 **`MINIQMT_USERDATA`** 指向 `userdata_mini`。  
4. 在 chan 环境中 `import xtquant` 可用（通常与 VeighNa 同一 Python 或 QMT 自带解释器）。  
5. 计算示例（单级别 5 分钟，代码为 QMT 格式；`CChan` 构造时会自动拉数据并完成计算）：

```python
from Chan import CChan
from Common.CEnum import KL_TYPE, AUTYPE

chan = CChan(
    "600519.SH",
    begin_time="20250501093000",
    end_time="20260508150000",
    lv_list=[KL_TYPE.K_5M],
    data_src="custom:XtQuant.CXtQuantStock",
    autype=AUTYPE.QFQ,
)
# 例如最近买卖点（以你本机 chan 版本 API 为准）
pts = chan.get_latest_bsp(number=5)
```

`begin_time` / `end_time` 会作为数据类构造参数里的 `begin_date` / `end_date` 传入 `XtQuant.py`（见 `Chan.py` 中 `get_load_stock_iter`）。

## 与 Streamlit 小页的关系

- **chan.py**：真缠论结构（笔、线段、中枢、bsp），适合 **回测与研究**。  
- **`examples/chan_web/app.py`**：轻量 K 线 + 分形，适合 **快速看图、给朋友演示**。  
二者可同时保留：研究用 chan 导出或截图，日常用 Streamlit。

## 数据深度提醒

你当前环境下 **分钟线约近一年、日线更长**；`begin_time` 设太早时分钟可能无 K 线，属 QMT 服务端/缓存限制，不是本适配类独有行为。
