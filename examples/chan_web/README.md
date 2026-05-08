# K 线 / 压力支撑 小网页（Streamlit）

**更推荐的研究路径**：用 **chan.py + miniQMT** 做真缠论结构，见同目录下的 [`integrate_chan_py/README.md`](integrate_chan_py/README.md)（将 `XtQuant.py` 拷入 chan 仓库 `DataAPI/`）。

本页（`app.py`）用于：**本机或局域网**快速看图、导出 CSV；内置 **三根 K 分形**仅为近似，**不等于** chan 的笔、中枢与买卖点。

## 安装

在仓库根目录 `Vnpy_Yue` 下：

```text
pip install -r examples/chan_web/requirements-chan-web.txt
```

## 本机运行

```text
streamlit run examples/chan_web/app.py
```

浏览器默认 <http://localhost:8501>。

## 给同一 WiFi 下的朋友访问

```text
streamlit run examples/chan_web/app.py --server.address 0.0.0.0 --server.port 8501
```

对方浏览器打开：`http://你的电脑局域网IP:8501`（Windows 可在 `ipconfig` 里看 IPv4）。

- 当前示例 **无登录、无 HTTPS**，仅适合信任环境。  
- 需要外网或鉴权时：自行加 VPN、云主机 + Nginx 基本认证，或查阅 Streamlit 官方 `secrets` / 社区鉴权方案。

## miniQMT

先启动 **QMT / miniQMT** 并保持登录。可选：

```text
set MINIQMT_USERDATA=D:\path\to\userdata_mini
```

## 与 chan.py 结合（思路）

1. 克隆 `chan.py`（建议 **Python 3.11+** 独立环境）。  
2. 按官方 [quick_guide.md](https://github.com/Vespa314/chan.py/blob/main/quick_guide.md) 在 `DataAPI` 下实现 **QMT 数据源类**（`get_kl_data` 产出 `CKLine_Unit`）。  
3. 用 `CChan` 算出笔/中枢/买卖点后，可 **导出 JSON** 或由另一进程画图；本页可先承担 **原始 OHLCV + 分形层**，再逐步替换为 chan 输出。

## CSV 格式

需包含列：`open, high, low, close, volume`（`volume` 可全 0），时间列名为 `datetime` 或 `time`，或为第一列。
