# 任务 5.1 完成报告：Generation Ranking（Top 100 计算）

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 完成

---

## 实现概述

实现了 Products 输出层的核心功能：年度发电量排名计算。支持计算全球水电站年度发电量 Top N，按国家分组排名，导出为多种格式（CSV、JSON、Markdown）。

---

## 核心文件

### 新增文件

- **hydro_platform/products/__init__.py** (315 行)
  - `GenerationRanking` 类：排名计算核心
  - `RankingConfig` 类：配置管理

### 测试文件

- **tests/test_generation_ranking.py** (8个测试，100%通过)

---

## 核心功能

### 1. 基础排名计算

计算指定年份的发电量 Top N：

```python
from hydro_platform.products import GenerationRanking
from hydro_platform.database.connection import connect

conn = connect()
ranking = GenerationRanking(conn)

# 计算 2023 年 Top 100
top100 = ranking.calculate_top_n(year=2023, limit=100)

for record in top100:
    print(f"{record['rank']}. {record['canonical_name']}: {record['generation_gwh']:.2f} GWh")
```

**筛选条件**（符合设计文档 §20.1）：
- `period_type = 'calendar_year'`（日历年）
- `value_type = 'actual'`（实际值，非估算）
- `measurement_scope = 'plant'`（全站口径）
- `review_status = 'approved'`（已审核）
- `publication_status = 'publishable'`（可发布）

### 2. 国家过滤

计算特定国家的排名：

```python
# 仅计算中国电站 Top 10
cn_top10 = ranking.calculate_top_n(year=2023, limit=10, country='CN')
```

### 3. 按国家分组排名

分别计算每个国家的 Top N：

```python
# 每个国家 Top 10
by_country = ranking.calculate_top_n_by_country(year=2023, limit_per_country=10)

# 结果: {'CN': [...], 'BR': [...], 'US': [...], ...}
for country, records in by_country.items():
    print(f"{country}: {len(records)} 个电站")
```

### 4. 统计信息

获取年度全局统计：

```python
stats = ranking.get_statistics(year=2023)

print(f"总记录数: {stats['total_records']}")
print(f"电站数: {stats['total_stations']}")
print(f"国家数: {stats['total_countries']}")
print(f"总发电量: {stats['total_generation_twh']:.2f} TWh")
print(f"平均发电量: {stats['avg_generation_gwh']:.2f} GWh")
```

### 5. CSV 导出

导出为 CSV 表格：

```python
from pathlib import Path

output_path = Path('outputs/rankings/top100_2023.csv')
ranking.export_to_csv(year=2023, output_path=output_path, limit=100)
```

**CSV 格式**：
```csv
rank,entity_id,canonical_name,country,capacity_mw,year,generation_gwh,unit,confidence_score,source_id
1,GEM-G100000601208,Three Gorges Dam,CN,22500,2023,98800.00,GWh,0.95,src_001
2,GEM-G100000604507,Itaipu Dam,BR,14000,2023,89100.00,GWh,0.92,src_002
...
```

### 6. JSON 导出

导出为 JSON 格式（可选包含统计信息）：

```python
output_path = Path('outputs/rankings/top100_2023.json')
ranking.export_to_json(
    year=2023,
    output_path=output_path,
    limit=100,
    include_stats=True  # 包含统计信息
)
```

**JSON 格式**：
```json
{
  "year": 2023,
  "limit": 100,
  "count": 100,
  "ranking": [
    {
      "rank": 1,
      "entity_id": "GEM-G100000601208",
      "canonical_name": "Three Gorges Dam",
      "country": "CN",
      "capacity_mw": 22500.0,
      "year": "2023",
      "generation_gwh": 98800.0,
      "unit": "GWh",
      "confidence_score": 0.95,
      "source_id": "src_001"
    },
    ...
  ],
  "statistics": {
    "total_records": 150,
    "total_stations": 150,
    "total_countries": 45,
    "total_generation_gwh": 4567890.5,
    "total_generation_twh": 4567.89,
    "avg_generation_gwh": 30452.6
  }
}
```

### 7. Markdown 报告

生成可读的 Markdown 报告：

```python
output_path = Path('outputs/rankings/top100_2023.md')
ranking.export_markdown_report(year=2023, output_path=output_path, limit=100)
```

**Markdown 格式示例**：

```markdown
# 全球水电站发电量 Top 100 (2023)

## 统计摘要

- **总记录数**: 150
- **电站数**: 150
- **国家数**: 45
- **总发电量**: 4567.89 TWh
- **平均发电量**: 30452.60 GWh

## 排名

| 排名 | 电站名称 | 国家 | 容量(MW) | 发电量(GWh) | 置信度 |
|------|---------|------|----------|-------------|--------|
| 1 | Three Gorges Dam | CN | 22500 | 98800.00 | 0.95 |
| 2 | Itaipu Dam | BR | 14000 | 89100.00 | 0.92 |
| 3 | Xiluodu Dam | CN | 13860 | 55620.00 | 0.90 |
...
```

---

## 测试结果

```
总计: 8/8 测试通过

✅ 基础排名计算
✅ 国家过滤
✅ 按国家分组排名
✅ 统计信息
✅ CSV导出
✅ JSON导出
✅ Markdown报告
✅ 配置
```

---

## 配置选项

```python
from hydro_platform.products import RankingConfig

# 默认排名数量
default_limit = RankingConfig.get_default_limit()  # 100

# 支持的统计口径
period_types = RankingConfig.get_supported_period_types()
# ['calendar_year', 'water_year', 'fiscal_year']

# 默认输出目录
output_dir = RankingConfig.get_default_output_dir()  # outputs/rankings
```

---

## 使用场景

### 场景1：生成年度 Top 100 报告

```python
from hydro_platform.products import GenerationRanking
from hydro_platform.database.connection import connect
from pathlib import Path

conn = connect()
ranking = GenerationRanking(conn)

# 生成完整报告
year = 2023
output_dir = Path('outputs/rankings')
output_dir.mkdir(parents=True, exist_ok=True)

# CSV（数据分析用）
ranking.export_to_csv(year, output_dir / f'top100_{year}.csv')

# JSON（API/前端用）
ranking.export_to_json(year, output_dir / f'top100_{year}.json', include_stats=True)

# Markdown（报告用）
ranking.export_markdown_report(year, output_dir / f'top100_{year}.md')

print(f"{year} 年 Top 100 报告已生成")
```

### 场景2：按国家生成排名

```python
# 每个国家 Top 20
by_country = ranking.calculate_top_n_by_country(year=2023, limit_per_country=20)

# 分别导出
for country, records in by_country.items():
    output_path = output_dir / f'top20_{country}_{year}.csv'
    # 手动写入CSV...
```

### 场景3：CLI 集成

可以在 CLI 中添加命令：

```python
# hydro_platform/app/cli/commands.py

@cli.command()
@click.option('--year', required=True, type=int)
@click.option('--limit', default=100, type=int)
@click.option('--format', type=click.Choice(['csv', 'json', 'markdown']), default='csv')
@click.option('--output', type=click.Path(), required=True)
def export_ranking(year: int, limit: int, format: str, output: str, db: str):
    """导出年度发电量排名"""
    conn = connect(db)
    ranking = GenerationRanking(conn)
    
    if format == 'csv':
        ranking.export_to_csv(year, Path(output), limit)
    elif format == 'json':
        ranking.export_to_json(year, Path(output), limit)
    elif format == 'markdown':
        ranking.export_markdown_report(year, Path(output), limit)
    
    click.echo(f"排名已导出到 {output}")
```

使用：
```bash
python -m hydro_platform.app.cli export-ranking --year 2023 --limit 100 --format csv --output top100_2023.csv
```

---

## 关键设计决策

1. **筛选条件严格**
   - 只包含已审核（approved）和可发布（publishable）的记录
   - 确保数据质量和权威性
   - 避免未验证数据进入公开排名

2. **使用 period_label 存储年份**
   - 数据库实际使用 `period_label` 字段存储年份（字符串）
   - 而非单独的 `year` 列（整数）
   - 适配现有数据库schema

3. **支持多种输出格式**
   - CSV：数据分析和Excel处理
   - JSON：API和前端集成
   - Markdown：可读报告和文档

4. **置信度处理**
   - 使用 `confidence` 字段（可能为NULL）
   - 导出时默认为0避免格式化错误

5. **按国家分组**
   - 支持全球排名和分国家排名
   - 满足不同维度的分析需求

---

## 局限性与后续优化

### 当前局限

1. **缺少多年对比**
   - 当前仅支持单年排名
   - 无法直接对比年度变化

2. **缺少容量利用率**
   - 仅计算发电量排名
   - 未计算发电量/容量比（利用率）

3. **缺少区域分组**
   - 仅支持按国家分组
   - 未支持按地区（亚洲、欧洲等）

### 优化方向

1. **多年趋势分析**
   ```python
   def calculate_trends(self, years: List[int], limit: int = 100):
       """计算多年趋势"""
       # 返回每年Top N及排名变化
   ```

2. **容量利用率排名**
   ```python
   def calculate_capacity_factor_ranking(self, year: int):
       """计算容量利用率排名"""
       # generation_gwh / (capacity_mw * 8760) * 100
   ```

3. **区域分组**
   ```python
   def calculate_top_n_by_region(self, year: int):
       """按地区分组排名"""
       # 需要添加 region 映射
   ```

4. **可视化导出**
   ```python
   def export_to_chart(self, year: int, output_path: Path):
       """导出为图表（使用 matplotlib）"""
   ```

---

## 相关任务

- ✅ Task 5.1: Products 输出层（Top 100 计算）
- ⏳ Task 6.1: 集成测试
- ⏳ Task 6.2: 补充文档
