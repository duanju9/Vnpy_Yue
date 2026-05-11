每日标的评分输出目录（与 data/ 分离）

相对路径：examples/miniqmt_research/daily_picks/

concept_sector_screen_csv.py 在未指定 --out 时，会把 CSV 写到这里，并生成带日期的文件名；同目录下会更新 latest_screen.csv（若被 Excel 等占用，脚本会临时写入 latest_screen_<时间戳>.csv 作为最新副本）。

name_cn 列：默认会先读 stock_cn_name，再对缺简称的标的调 xtdata 补全（需 miniQMT）；离线请加参数 --skip-xt-name-fill。

本目录已纳入版本库；若本地看不到，请在资源管理器中打开上述路径，或在仓库根执行一次该脚本以生成 CSV。
