chan.py 已克隆在子目录 chan/（见 .gitignore，勿把整个 vendor/chan 提交到本仓库）。

## 已替你放好

- `chan/DataAPI/XtQuant.py` 已从 `examples/chan_web/integrate_chan_py/XtQuant.py` 复制一份。  
  以后若改适配逻辑，请**先改 integrate_chan_py/XtQuant.py**，再复制覆盖到此处。

## 独立环境（建议 Python 3.11+）

在任意目录（或进入 chan/）：

  pip install -r d:\Vnpy\Vnpy_Yue\examples\chan_web\vendor\chan\Script\requirements.txt

启动 miniQMT；需要时设置 MINIQMT_USERDATA。

## 最小示例

  cd d:\Vnpy\Vnpy_Yue\examples\chan_web\vendor\chan
  python -c "from Chan import CChan; from Common.CEnum import KL_TYPE, AUTYPE; CChan('600519.SH', begin_time='20250501093000', end_time='20260508150000', lv_list=[KL_TYPE.K_5M], data_src='custom:XtQuant.CXtQuantStock', autype=AUTYPE.QFQ)"

时间范围与周期以你本机 QMT 数据为准。
