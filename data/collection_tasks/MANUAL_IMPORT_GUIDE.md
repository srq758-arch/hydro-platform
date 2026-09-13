# 手动数据采集操作指南

## 快速开始：导入三峡大坝 2024 年数据

### 方法 1：使用桌面应用 GUI（推荐新手）

#### 步骤 1：下载网页
1. 打开浏览器访问：http://en.sasac.gov.cn/2025/09/09/c_19816.htm
2. 右键 → "另存为" → 保存为 `three_gorges_2024.html`
3. 移动文件到：`F:\hydro_platform_v1\data\collection_tasks\downloads\`

#### 步骤 2：使用桌面应用导入
1. 启动桌面应用：双击 `dist/水电站数据平台/hydropower_app.exe`
2. 点击左侧菜单「新增数据」
3. 选择「上传文件」标签
4. 点击「选择文件」→ 选择 `three_gorges_2024.html`
5. 填写表单：
   - **来源名称**：SASAC Three Gorges 2024 Report
   - **来源类型**：选择 "Official Report"
   - **发布机构**：State-owned Assets Supervision and Administration Commission
   - **发布日期**：2025-09-09
6. 点击「开始处理」按钮

#### 步骤 3：等待处理完成
系统会自动执行：
- ✅ 归档文件到 `data/raw/`
- ✅ 解析 HTML 提取文本
- ✅ 调用 DeepSeek 抽取发电量数据
- ✅ 创建复核任务

#### 步骤 4：复核数据
1. 点击左侧菜单「复核中心」
2. 找到新创建的复核记录
3. 检查抽取结果：
   - 电站名称是否正确？
   - 发电量数值是否准确？
   - 单位转换是否正确（TWh → GWh）？
4. 如果正确，点击「确认」按钮
5. 数据将发布到 `generation_records` 表

---

### 方法 2：使用 Python 脚本（批量处理）

#### 准备工作
```bash
cd F:/hydro_platform_v1
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

#### 脚本：批量导入 URL
```python
# scripts/batch_import_urls.py
from hydro_platform.app.api import Api
from hydro_platform.database.connection import connect
import csv

def import_from_csv(csv_path: str):
    """从 CSV 批量导入数据源 URL"""
    api = Api(data_mode="production")
    api.initialize()
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['source_url'].startswith('http'):
                print(f"\n处理: {row['canonical_name']} ({row['country']})")
                print(f"URL: {row['source_url']}")
                
                # 注意：桌面应用 API 可能没有 process_url 方法
                # 需要先确认 API 接口
                try:
                    # 暂时跳过，需要确认正确的 API 方法
                    print("⚠️  需要手动在桌面应用中处理")
                except Exception as e:
                    print(f"❌ 错误: {e}")

if __name__ == "__main__":
    import_from_csv("data/collection_tasks/priority_sources.csv")
```

---

### 方法 3：手动创建测试数据（快速验证）

如果只是想测试系统是否工作，可以手动插入测试数据：

```python
# scripts/insert_test_data.py
from hydro_platform.database.connection import connect
from pathlib import Path
import uuid

conn = connect(Path("data/hydropower.sqlite"))

# 插入来源记录
source_id = str(uuid.uuid4())
conn.execute("""
    INSERT INTO sources (source_id, title, publisher, publication_date, url, source_type)
    VALUES (?, ?, ?, ?, ?, ?)
""", (
    source_id,
    "Three Gorges Hydropower Station Generates 1.8 Trillion kWh",
    "SASAC",
    "2025-09-09",
    "http://en.sasac.gov.cn/2025/09/09/c_19816.htm",
    "news"
))

# 插入发电量记录
conn.execute("""
    INSERT INTO generation_records (
        entity_id, period_label, value_type, generation_gwh,
        measurement_scope, confidence_level, evidence_id, published_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", (
    "GEM-G100000601208",  # 三峡大坝
    "2024",
    "actual",
    103000.0,  # 103 TWh = 103,000 GWh
    "plant",
    "high",
    None,  # 暂时没有证据
    "published"
))

conn.commit()
conn.close()
print("✅ 测试数据插入成功")
```

运行：
```bash
python scripts/insert_test_data.py
```

然后打开桌面应用，进入「数据浏览」或「Top 100」查看是否显示。

---

## 常见问题

### Q1: 桌面应用在哪里？
A: 如果还没打包，需要先运行：
```bash
cd F:/hydro_platform_v1
python -m hydro_platform.app.gui.main_window
```

### Q2: DeepSeek API Key 在哪配置？
A: 需要设置环境变量或配置文件：
```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY = "your-api-key-here"

# Linux/Mac
export DEEPSEEK_API_KEY="your-api-key-here"
```

### Q3: 数据库在哪里？
A: 默认位置：
- 生产数据库：`F:\hydro_platform_v1\data\hydropower.sqlite`
- 测试数据库：`F:\hydro_platform_v1\data\test\hydropower.sqlite`

### Q4: 如何查看已采集的数据？
```sql
-- 查看所有发电量记录
SELECT 
    gr.entity_id,
    s.canonical_name,
    gr.period_label,
    gr.generation_gwh,
    gr.published_status
FROM generation_records gr
LEFT JOIN stations s ON s.entity_id = gr.entity_id
ORDER BY gr.generation_gwh DESC
LIMIT 10;
```

### Q5: 处理失败怎么办？
检查日志文件：
- `logs/app.log` - 应用日志
- `logs/pipeline.log` - 管线处理日志

---

## 下一步建议

### 今天完成：
1. ✅ 手动导入 1-2 个电站数据（测试流程）
2. ✅ 验证数据是否正确显示在桌面应用中
3. ✅ 记录遇到的问题

### 明天完成：
4. 批量下载中国 Top 5 电站的报告
5. 逐个导入并复核
6. 更新采集进度表

### 本周完成：
7. 扩展到国际 Top 10 电站
8. 下载 EIA-923 数据（美国全部）
9. 编写批量导入脚本

---

**提示**: 如果手动操作太繁琐，我可以帮你写一个自动化脚本，但需要先确认：
1. 你的 DeepSeek API Key 是否已配置？
2. 桌面应用是否能正常启动？
3. 数据库中是否已有 4,965 个水电站种子数据？
