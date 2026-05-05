# GitHub 同步：master 推送与 README_ENG 恢复说明

- 日期：2026-05-05（北京时间，会话收尾阶段）
- 范围：仓库 `Vnpy_Yue` 整包提交并推送至 GitHub；**无业务代码变更**，仅版本库状态与留档说明
- 关联：**commit `85ee97f`**，`origin/master` ← `https://github.com/duanju9/Vnpy_Yue.git`
- 触发动机：用户要求「把今天的内容上传到 GitHub 补充」，并要求将本次操作**记录留存**

---

## 一、做了什么

### 1) 纳入本次 commit 的路径（`git add`）

| 类型 | 路径 |
|------|------|
| 包 | `vnpy/feeds/`（`__init__.py`、`bars_io.py`、`cached_daily.py`、`daily_store.py`、`paths.py`、`registry.py`、`tsy_pro.py`） |
| 示例与脚本 | `examples/quick_tests/`（`dual_ma_smoketest.py`、`run_dual_ma_cta_backtest.py`、`cache_smoke.py`） |
| 示例配套 | `examples/tsy_xiaodefa_client.py`、`examples/requirements-cta.txt`、`examples/requirements-tsy.txt`、`examples/setup_tsy.ps1`、`examples/.env.example` |
| 文档 | `docs/dev_log/2026-05-05_002_data_cache_architecture.md`、`docs/dev_log/README.md` |
| 工程 | `.gitignore`、`pyproject.toml` |

### 2) 刻意不提交的内容（`.gitignore` 已覆盖）

- `examples/quick_tests/output/` — 本地 HTML / JSON / CSV 报表
- `data/vnpy_yue/` — Parquet 与 `manifest.sqlite` 缓存
- `examples/quick_tests/cta_bt_workspace/` — CTA 脚本独立 SQLite

### 3) `README_ENG.md` 处理

- **现象**：工作区中 `README_ENG.md` 处于删除状态，但根目录 `README.md` 仍包含指向 `README_ENG.md` 的链接。
- **操作**：执行 `git checkout HEAD -- README_ENG.md`，从当前 `HEAD` **恢复该文件**，再与上述变更一并提交，避免远程仓库出现**断链**。
- **若后续要下线英文 README**：应同时修改 `README.md` 中的链接或改为单一文档结构，再单独提交。

### 4) 推送结果

```text
git push origin master
# To https://github.com/duanju9/Vnpy_Yue.git
#    86510e0..85ee97f  master -> master
```

---

## 二、怎么验证（可复现）

本机已有该 commit 时：

```powershell
Set-Location d:\Vnpy\Vnpy_Yue
git fetch origin
git log -1 --oneline origin/master
# 期望：85ee97f feat: 日线缓存基座、双均线烟雾测试与 CTA 回测脚本
```

新机器对齐：

```powershell
git clone https://github.com/duanju9/Vnpy_Yue.git
cd Vnpy_Yue
git checkout master
```

---

## 三、未决事项 / 下一篇可记

- 若需要 **dev_log 001**（双均线烟雾测试专项说明）与 **002** 并列归档，可从对话摘要补一篇 `2026-05-05_001_dual_ma_smoketest.md`（当前仓库仅有 002）。
- 明日继续：按用户节奏拉 `git pull`，再迭代图表对齐 / DuckDB 分析层等。
