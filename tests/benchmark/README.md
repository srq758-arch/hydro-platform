# Ground Truth Benchmark 说明

## 概述

本目录包含 Ground Truth Benchmark 评估系统，用于验证数据采集和抽取的准确性。

## 目录结构

```
tests/benchmark/
├── ground_truth/
│   └── station_generation_cases.json    # Ground Truth 测试样本（20条）
├── reports/                             # 评估报告输出目录
├── benchmark_runner.py                  # Benchmark 运行器
├── evaluator.py                         # 评估指标计算
├── report_generator.py                  # 报告生成器
└── README.md                           # 本文件
```

## Ground Truth 样本格式

每个测试样本包含：

```json
{
  "case_id": "gt_001",
  "entity_id": "CHN_three_gorges_dam",
  "canonical_name": "Three Gorges Dam",
  "country": "China",
  "year": 2023,
  "period_type": "calendar_year",
  "expected_generation_gwh": 87800.0,
  "expected_unit": "GWh",
  "source_url": "https://www.ctg.com.cn/...",
  "evidence_reference": "三峡集团2023年生产经营情况",
  "notes": "官方数据",
  "source_type": "official",
  "manually_verified": true,
  "verified_by": "researcher",
  "verified_date": "2026-09-08"
}
```

## 运行 Benchmark

### 方法1：使用 CLI 命令

```bash
python -m hydro_platform.app.cli benchmark \
  --ground-truth tests/benchmark/ground_truth/station_generation_cases.json \
  --output tests/benchmark/reports
```

### 方法2：使用 Python 脚本

```python
from pathlib import Path
from tests.benchmark import BenchmarkRunner, BenchmarkEvaluator, ReportGenerator

# 运行 Benchmark
runner = BenchmarkRunner(
    ground_truth_path=Path("tests/benchmark/ground_truth/station_generation_cases.json")
)
results = runner.run_all()

# 评估
evaluator = BenchmarkEvaluator()
report = evaluator.calculate_metrics(results)

# 生成报告
generator = ReportGenerator()
generator.generate_markdown(report, Path("tests/benchmark/reports/benchmark_report.md"))

print(f"整体准确率: {report.overall_record_accuracy:.1%}")
```

## 评估指标

### 阶段成功率
- **source_discovery_rate**: 来源发现成功率
- **acquisition_success_rate**: 资料获取成功率
- **parse_success_rate**: 内容解析成功率
- **extraction_success_rate**: 数据抽取成功率

### 字段准确率
- **entity_match_accuracy**: 电站实体匹配准确率
- **year_accuracy**: 年份识别准确率
- **unit_accuracy**: 单位识别准确率

### 值准确度
- **value_accuracy**: 发电量数值准确度（允许5%误差）

### 整体准确率
- **overall_record_accuracy**: 整体记录准确率（目标 ≥ 80%）

## 准确度计算规则

发电量值准确度：
- 误差 ≤ 5%: 100%
- 误差 ≤ 10%: 90%
- 误差 ≤ 20%: 70%
- 误差 > 20%: 根据误差率线性递减

整体判定：
- 电站匹配 ✓
- 年份正确 ✓
- 单位正确 ✓
- 值准确度 ≥ 95% ✓
→ 记录判定为 PASS

## 样本选择原则

当前 20 条样本覆盖：
- 10 条超大型电站（>5000 MW）
- 5 条中型电站（1000-5000 MW）
- 5 条小型电站（<1000 MW）
- 7 个国家
- 多种数据源类型（官方年报、监管机构、API）

## 添加新样本

1. 手动验证数据准确性
2. 在 `station_generation_cases.json` 中添加新条目
3. 确保 `manually_verified: true`
4. 记录验证人和验证日期

## 注意事项

1. **Ground Truth 必须人工核实**，不能根据程序输出反向修改
2. **样本应保持稳定**，避免频繁变更
3. **URL 应使用可长期访问的来源**，避免链接失效
4. **定期更新样本**，确保年份和数据时效性

## 故障排查

如果准确率低于预期：

1. 检查失败案例的 `error_stage` 和 `error_message`
2. 查看评估报告中的"改进建议"部分
3. 针对性优化相应模块（Discovery / Acquisition / Parsing / Extraction）
4. 重新运行 Benchmark 验证改进效果
