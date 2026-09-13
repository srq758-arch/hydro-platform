# Ground Truth Benchmark 使用指南

## 什么是Ground Truth Benchmark？

**Ground Truth（基准真值）** = 人工验证的标准答案

用于量化系统准确率：

```
系统声称：三峡大坝2023年发电量 = 88.6 GWh
Ground Truth：人工查证官方数据 = 88.6 GWh
结果：✓ 完全匹配

系统声称：某电站2023年发电量 = 50.0 GWh
Ground Truth：人工查证官方数据 = 52.3 GWh
结果：✗ 误差 4.4%
```

---

## 为什么需要？

### 问题
- 系统找到数据，但**不知道是否准确**
- 无法回答"准确率多少？"

### 解决
- 人工标注20-30个测试案例
- 建立"标准答案"数据集
- 量化系统表现：准确率85%

---

## 工作流程

```
1. 创建测试案例
   - 从数据库随机选择20个电站
   - 选择近3年数据
   ↓
2. 人工标注
   - 访问官方网站
   - 查证真实数据
   - 记录标准答案
   ↓
3. 系统评估
   - 对比系统输出 vs 标准答案
   - 计算准确率、误差
   ↓
4. 生成报告
   - 覆盖率
   - 准确率
   - 平均误差
```

---

## 使用方法

### 方式1: 交互式标注（推荐）

```bash
cd F:\hydro_platform_v1
python tools/ground_truth_benchmark.py
```

#### 步骤1: 创建测试案例

```
选择功能:
1. 创建并标注测试案例
2. 评估基准测试

请选择 (1/2): 1

[步骤1] 创建测试案例
1. 创建新的测试案例
2. 加载已有测试案例

请选择 (1/2): 1

创建多少个案例? (默认20): 20

已创建 20 个测试案例
文件: data/ground_truth/benchmark_20260907_143052.json
```

#### 步骤2: 人工标注

```
[步骤2] 标注案例
为每个案例填写标准答案（人工查证）

标注人员姓名: 张三

--- 案例 1/20 ---
电站: Three Gorges Dam
国家: China
装机: 22500 MW
年份: 2023
官网: https://www.ctg.com.cn

请访问官方网站或权威数据源，查证该年份的发电量

标注此案例? (y/n/quit): y

发电量 (GWh): 88600
数据来源URL: https://www.ctg.com.cn/reports/annual-2023.pdf
备注 (可选): 来自三峡集团年报第15页

✓ 已标注

--- 案例 2/20 ---
...
```

**标注提示**:
- 访问官方网站查找年报
- 如果官网没有，查EIA、IEA等权威数据源
- 记录数据来源URL，方便复核
- 如果找不到，输入 `n` 跳过

#### 步骤3: 评估

标注完成后，运行评估：

```bash
python tools/ground_truth_benchmark.py

选择功能:
1. 创建并标注测试案例
2. 评估基准测试

请选择 (1/2): 2

可用的基准文件:
1. benchmark_20260907_143052.json (15/20 已标注)

选择文件 (输入编号): 1

开始评估...

============================================================
Ground Truth Benchmark 评估报告
============================================================

基准文件: benchmark_20260907_143052.json
评估时间: 2026-09-07T14:45:23

测试案例数: 15
系统覆盖: 12/15 (80.0%)

准确性指标:
  完全匹配: 10/12 (83.3%)
  接近匹配(<5%误差): 11/12 (91.7%)
  平均误差: 2.34%

详细结果:
案例                                     标准值       系统值       误差        状态
--------------------------------------------------------------------------------
CHN_three_gorges_dam_2023                88600.0      88600.0      0.0%       ✓
CHN_xiluodu_dam_2023                     60800.0      60800.0      0.0%       ✓
CHN_baihetan_dam_2023                    62430.0      N/A          N/A        -
USA_hoover_dam_2023                      4000.0       3950.0       1.3%       ✓
...

============================================================

保存评估结果? (y/n): y
已保存: data/ground_truth/evaluation_20260907_144523.json
```

---

### 方式2: 编程使用

```python
from pathlib import Path
from tools.ground_truth_benchmark import GroundTruthManager

# 初始化
db_path = Path("data/hydropower.sqlite")
manager = GroundTruthManager(db_path)

# 1. 创建测试案例
test_cases = manager.create_test_cases(num_cases=20)
filepath = manager.save_test_cases(test_cases)

# 2. 手动编辑JSON文件，填写ground_truth

# 3. 评估
evaluation = manager.evaluate_benchmark("benchmark_20260907_143052.json")
manager.print_evaluation_report(evaluation)

# 4. 保存评估结果
manager.save_evaluation(evaluation)
```

---

## 数据格式

### 基准文件格式

`data/ground_truth/benchmark_YYYYMMDD_HHMMSS.json`:

```json
{
  "created_at": "2026-09-07T14:30:52",
  "total_cases": 20,
  "annotated_cases": 15,
  "test_cases": [
    {
      "case_id": "CHN_three_gorges_dam_2023",
      "entity_id": "CHN_three_gorges_dam",
      "station_name": "Three Gorges Dam",
      "country": "China",
      "capacity_mw": 22500,
      "official_website": "https://www.ctg.com.cn",
      "year": 2023,
      "metric": "generation",
      "ground_truth": 88600.0,
      "annotated": true,
      "annotation_date": "2026-09-07T14:35:12",
      "annotator": "张三",
      "source_url": "https://www.ctg.com.cn/reports/annual-2023.pdf",
      "notes": "来自三峡集团年报第15页"
    }
  ]
}
```

### 评估结果格式

`data/ground_truth/evaluation_YYYYMMDD_HHMMSS.json`:

```json
{
  "benchmark_file": "benchmark_20260907_143052.json",
  "evaluation_date": "2026-09-07T14:45:23",
  "total_cases": 15,
  "covered_cases": 12,
  "coverage_rate": 80.0,
  "exact_matches": 10,
  "exact_accuracy": 83.3,
  "close_matches": 11,
  "close_accuracy": 91.7,
  "avg_error_pct": 2.34,
  "results": [
    {
      "case_id": "CHN_three_gorges_dam_2023",
      "station": "Three Gorges Dam",
      "year": 2023,
      "ground_truth": 88600.0,
      "system_output": 88600.0,
      "error_gwh": 0.0,
      "error_pct": 0.0,
      "match": true
    }
  ]
}
```

---

## 评估指标说明

### 1. 覆盖率 (Coverage Rate)

```
覆盖率 = 系统有输出的案例数 / 总案例数

示例：
- 总案例数: 15
- 系统有输出: 12
- 覆盖率: 80%

含义：系统能找到数据的能力
```

### 2. 完全匹配率 (Exact Accuracy)

```
完全匹配 = 误差 < 0.1 GWh

完全匹配率 = 完全匹配案例数 / 覆盖案例数

示例：
- 覆盖案例: 12
- 完全匹配: 10
- 完全匹配率: 83.3%

含义：系统输出完全准确的比例
```

### 3. 接近匹配率 (Close Accuracy)

```
接近匹配 = 误差 < 5%

接近匹配率 = 接近匹配案例数 / 覆盖案例数

示例：
- 覆盖案例: 12
- 接近匹配: 11
- 接近匹配率: 91.7%

含义：系统输出基本准确的比例（允许小误差）
```

### 4. 平均误差 (Average Error)

```
平均误差 = Σ(|系统值 - 标准值| / 标准值 * 100%) / 覆盖案例数

示例：
- 案例1误差: 0%
- 案例2误差: 1.3%
- 案例3误差: 5.2%
- ...
- 平均误差: 2.34%

含义：系统输出的平均偏差程度
```

---

## 最佳实践

### 1. 测试案例选择

**推荐**:
- 20-30个案例（够用且标注工作量可控）
- 覆盖不同国家
- 覆盖不同容量级别
- 选择有官方网站的电站（容易验证）

**避免**:
- 太少（<10个，不够代表性）
- 太多（>50个，标注工作量大）
- 全选大型电站（不能代表全貌）

### 2. 标注标准

**数据来源优先级**:
1. 电站官方网站年报
2. 国家权威机构（EIA、NEA等）
3. 国际组织（IEA、世界银行）
4. 学术论文、新闻报道（需多方验证）

**标注要求**:
- 记录数据来源URL
- 如有多个来源，选择最权威的
- 如果数据不一致，在备注中说明
- 无法查证的案例可以跳过

### 3. 定期更新

```
第一次评估（20案例）
  ↓
系统优化
  ↓
第二次评估（增加10案例）
  ↓
继续优化
  ↓
第三次评估（累计50案例）
```

建议：
- 初期：20案例，快速建立基准
- 系统稳定后：扩展到50案例
- 每次大更新后重新评估

---

## 标注示例

### 示例1: 三峡大坝

```
电站: Three Gorges Dam
年份: 2023
官网: https://www.ctg.com.cn

步骤:
1. 访问官网
2. 找到"投资者关系" → "年度报告"
3. 下载 2023年年报PDF
4. 查找"三峡电站发电量"章节
5. 找到数据: 88.6 TWh = 88600 GWh

标注:
发电量: 88600
来源: https://www.ctg.com.cn/reports/annual-2023.pdf
备注: 年报第15页，表3-1
```

### 示例2: 美国电站

```
电站: Hoover Dam
年份: 2023
官网: https://www.usbr.gov/lc/hooverdam/

步骤:
1. 官网没有详细数据
2. 访问EIA: https://www.eia.gov
3. 搜索 "Hoover Dam generation 2023"
4. 找到数据: 4.0 TWh = 4000 GWh

标注:
发电量: 4000
来源: https://www.eia.gov/electricity/data/browser/
备注: EIA官方统计
```

---

## 故障排查

### 问题1: 找不到数据

**症状**: 无法在官网或权威机构找到数据

**解决**:
1. 检查电站官网的"新闻"、"公告"栏目
2. 搜索电站名称 + 年份 + "发电量"
3. 查看国家统计局网站
4. 如果仍找不到，标记为"跳过"

### 问题2: 数据不一致

**症状**: 不同来源的数据不同

**示例**:
- 官网: 88.6 TWh
- EIA: 88.2 TWh
- 新闻: 89.0 TWh

**解决**:
1. 优先使用官方来源（官网 > EIA）
2. 在备注中说明差异
3. 选择最可靠的数据作为标准

### 问题3: 单位转换

**常见单位**:
- TWh (太瓦时) = 1000 GWh
- GWh (吉瓦时) = 1000 MWh
- MWh (兆瓦时) = 1000 kWh
- 亿千瓦时 = 100 GWh

**示例**:
- 年报: 886亿千瓦时
- 转换: 886 / 10 = 88.6 GWh

---

## 结果解读

### 场景1: 高准确率

```
覆盖率: 95%
完全匹配率: 90%
平均误差: 1.5%

解读: 系统表现优秀，可以投入生产使用
建议: 继续监控，定期更新基准
```

### 场景2: 中等准确率

```
覆盖率: 80%
完全匹配率: 75%
平均误差: 5.2%

解读: 系统基本可用，但有改进空间
建议:
- 分析错误案例
- 优化Discovery策略
- 改进数据抽取规则
```

### 场景3: 低准确率

```
覆盖率: 60%
完全匹配率: 50%
平均误差: 15.3%

解读: 系统需要重大改进
建议:
- 检查数据来源质量
- 改进解析逻辑
- 增加更多来源类型
```

---

## 持续改进

### 1. 分析错误案例

```python
# 查看误差最大的案例
evaluation = manager.evaluate_benchmark("benchmark.json")

errors = sorted(
    [r for r in evaluation['results'] if r['error_pct'] is not None],
    key=lambda x: x['error_pct'],
    reverse=True
)

print("误差最大的5个案例:")
for r in errors[:5]:
    print(f"{r['station']}: 误差{r['error_pct']:.1f}%")
```

### 2. 针对性优化

```
错误类型1: 单位转换错误
→ 改进单位识别规则

错误类型2: 数据来源不准确
→ 补充官方网站到stations表

错误类型3: 解析失败
→ 优化PDF解析逻辑
```

### 3. 重新评估

```
优化后 → 重新运行评估 → 对比改进前后
```

---

## API参考

### GroundTruthManager

#### `create_test_cases(num_cases=20)`
创建测试案例

**返回**: `List[Dict]`

---

#### `save_test_cases(test_cases, filename=None)`
保存测试案例

**返回**: 文件路径

---

#### `load_test_cases(filename)`
加载测试案例

**返回**: `Dict`

---

#### `annotate_case(case_id, ground_truth, source_url, annotator, notes="")`
标注单个案例

**返回**: 标注信息字典

---

#### `evaluate_benchmark(benchmark_file)`
评估基准测试

**返回**: 评估结果字典

---

#### `save_evaluation(evaluation, filename=None)`
保存评估结果

**返回**: 文件路径

---

## 总结

Ground Truth Benchmark是**质量保障**的关键工具：

1. **创建** 20个测试案例
2. **标注** 人工查证标准答案
3. **评估** 计算系统准确率
4. **优化** 针对性改进
5. **重复** 持续提升质量

投入：2-4小时标注工作  
产出：量化的准确率指标 + 改进方向

---

**文档版本**: v1.0  
**更新日期**: 2026-09-07  
**作者**: Claude Code
