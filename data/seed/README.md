# GEM Master Seed List (V1)

- 数据源：Global Energy Monitor（GEM）Global Hydropower Tracker，March 2026 release。
- 原始文件：`data/seed/gem_raw/GEM_GHPT_2026-03.xlsx`
- 生成日期：2026-08-30
- 主表记录：7023；其中 station：4965，project：2058。

## 文件

- `master_registry.csv`：完整主注册表，包含 Data 和 Below Threshold 两个工作表。
- `station_seed_list.csv`：Operating/Retired/Mothballed 等 station-like 记录。
- `project_seed_list.csv`：Announced/Construction/Pre-construction 及其他非 station-like 记录。
- `seed_import_report.json`：导入统计和质量检查。
- `gem_raw/`：不可修改的原始下载文件。

## 重要说明

1. 一行保留为一个 GEM unit/project row；同一 `gem_location_id` 出现多行时不擅自合并，因为它可能对应不同容量、状态或机组。
2. `entity_id` 优先由 GEM unit ID 生成，`gem_location_id` 和 `gem_unit_id` 都保留以便回溯。
3. 该列表是候选实体基础，不是年度发电量 Ground Truth，也不是最终 Top 100。
4. GEM 数据许可为 CC BY 4.0；对外发布时应保留 GEM 署名。
5. 年度发电量应写入独立的 GenerationRecord 表，并关联来源和证据。

来源页面：https://globalenergymonitor.org/projects/global-hydropower-tracker
下载地址（本次原始文件获取地址）：https://zenodo.org/api/records/20843067/files/GEM_GHPT.xlsx/content
