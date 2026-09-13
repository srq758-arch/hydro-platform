# hydro-platform

全球水电站数据采集与核验系统 V1 —— 任务驱动、证据可追溯。

采集全球水电站的基本信息与年度发电量，为每一条数据保留来源与证据链，而不是只存一个结果值。

## 运行环境

- Python >= 3.11
- 默认入口是桌面应用（基于 pywebview）

## 安装

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e .
```

按需安装可选依赖：

```bash
pip install -e ".[parsing]"   # PDF / xlsx 解析
pip install -e ".[browser]"   # Playwright 路由回退（步骤 6）
pip install -e ".[dev]"       # 测试
```

未安装可选依赖时对应能力会优雅降级，不会导致崩溃。

## 运行

```bash
hydro-platform
```

## 测试

```bash
pytest
```

默认只跑不依赖外部环境的用例。需要真实外网、浏览器、LLM 凭据或打包环境的用例已用 marker 隔离，显式开启：

```bash
pytest -m network
pytest -m browser
pytest -m llm
pytest -m packaging
```

## 凭据

API 密钥不落库、不进仓库。优先走系统凭据存储（Windows 下为 Credential Manager，经由 `keyring`），
配置文件位于用户目录 `~/.hydro_platform/`，加密存储。

## 数据来源与署名

本仓库 `data/` 下的部分数据来自第三方，需遵守其原始许可。

### Global Energy Monitor — Global Hydropower Tracker

- **来源**：[Global Hydropower Tracker](https://globalenergymonitor.org/projects/global-hydropower-tracker)，Global Energy Monitor
- **版本**：March 2026 release
- **原始文件**：`data/seed/gem_raw/GEM_GHPT_2026-03.xlsx`（原始下载文件，未修改）
- **许可**：[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

以下文件由上述原始文件**派生转换**而来（重命名列、拆分工作表、补充内部主键与校验字段），
内容不代表 GEM 的原始排版：

- `data/seed/master_registry.csv`
- `data/seed/station_seed_list.csv`
- `data/seed/project_seed_list.csv`
- `data/seed/seed_import_report.json`

按 CC BY 4.0 要求，使用或再分发上述数据时请保留本节署名，并注明是否做过修改。

### 其他

`data/raw/` 下为采集阶段抓取的公开网页与文档存档，版权归各自原始发布方所有，
**不在本仓库的许可范围内**，请勿单独再分发。`data/collection_tasks/priority_sources.csv`
中记录的各条 `source_url` 为对应的原始来源。

## 许可

本仓库自有代码的许可见 [LICENSE](LICENSE)。
