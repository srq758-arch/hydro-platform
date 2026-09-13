# 全球水电数据采集行动计划

**创建日期**: 2026-09-06  
**目标**: 为 Top 100 水电站收集 2023-2025 年度发电量数据

---

## 一、已识别的数据源

### 1. 中国水电站（优先级最高）
**数据源**: 国务院国资委官网 (SASAC)  
**网址**: http://en.sasac.gov.cn/  
**覆盖范围**: 三峡集团运营的所有大型水电站

#### 已确认电站：
- ✅ **三峡大坝** (22,500 MW) - [数据链接](http://en.sasac.gov.cn/2025/09/09/c_19816.htm)
  - 2024年累计: 1.8万亿千瓦时
  - 年度约: 103 TWh
  
- ✅ **白鹤滩** (16,000 MW) - [数据链接](http://en.sasac.gov.cn/2023/10/17/c_16059.htm)
  - 2023年: 62.44 TWh (设计容量)
  
- 🔍 **待搜索**: 溪洛渡、乌东德、向家坝、龙滩、锦屏等

### 2. 巴西/巴拉圭水电站
**数据源**: Itaipu Binacional 官网  
**网址**: https://www.itaipu.gov.py/  

#### 已确认电站：
- ✅ **伊泰普** (14,000 MW) - [2025数据](https://www.itaipu.gov.py/noticias/energia/itaipu-suministro-25-768-gwh-de-energia-electrica-a-paraguay-en-el-2025)
  - 2025年: 72.879 TWh
  - 2024年: 67.127 TWh

- 🔍 **待搜索**: Belo Monte, Tucuruí, Jirau, Santo Antônio

### 3. 美国水电站（批量数据）
**数据源**: EIA-923 官方数据  
**网址**: https://www.eia.gov/electricity/data/detail-data.php  
**覆盖**: 所有美国水电站 2003-2024 年数据

**替代源**: ORNL Hydrosource  
**网址**: https://hydrosource.ornl.gov/data/datasets/eha-net-generation-plant-database-2003-2024/

#### 包含电站（部分）：
- Grand Coulee Dam (6,809 MW)
- Chief Joseph Dam
- John Day Dam
- 等数百个电站

### 4. 俄罗斯水电站
🔍 **待识别数据源**: 
- RusHydro 官网
- Sayano-Shushenskaya, Krasnoyarsk, Bratsk 等

### 5. 加拿大水电站
🔍 **待识别数据源**:
- Hydro-Québec
- BC Hydro
- Churchill Falls, Robert-Bourassa 等

---

## 二、数据采集策略

### 阶段 1: 手动采集（本周）
**目标**: 10-15 个重点电站  
**方法**: 使用桌面应用「新增数据」功能

1. **中国 Top 5 电站**
   - 三峡、白鹤滩、溪洛渡、乌东德、向家坝
   - 数据源: SASAC 官网新闻稿

2. **国际 Top 5 电站**
   - Itaipu (巴西/巴拉圭)
   - Grand Ethiopian Renaissance (埃塞俄比亚)
   - Guri (委内瑞拉)
   - Tucuruí (巴西)
   - Robert-Bourassa (加拿大)

### 阶段 2: 批量采集（下周）
**目标**: 美国全部水电站  
**方法**: 
1. 下载 EIA-923 Excel 文件
2. 写 Python 脚本批量导入
3. 自动创建 `tasks` 记录

### 阶段 3: 爬虫自动化（后续）
**目标**: 定期更新所有电站数据  
**方法**:
1. 为每个数据源开发 URL 解析器
2. 实现 `UrlResolver` 类
3. 定时任务自动采集

---

## 三、具体操作步骤（今天开始）

### Step 1: 准备测试数据
我已为你找到的数据源：

| 电站 | 国家 | 容量 | 数据链接 |
|------|------|------|----------|
| 三峡大坝 | 中国 | 22,500 MW | [SASAC](http://en.sasac.gov.cn/2025/09/09/c_19816.htm) |
| 白鹤滩 | 中国 | 16,000 MW | [SASAC](http://en.sasac.gov.cn/2023/10/17/c_16059.htm) |
| Itaipu | 巴西/巴拉圭 | 14,000 MW | [Itaipu官网](https://www.itaipu.gov.py/noticias/energia/itaipu-suministro-25-768-gwh-de-energia-electrica-a-paraguay-en-el-2025) |

### Step 2: 下载 PDF/HTML 文档
```bash
# 示例：使用 wget 下载
wget -O three_gorges_2024.html "http://en.sasac.gov.cn/2025/09/09/c_19816.htm"
```

### Step 3: 使用桌面应用导入
1. 启动桌面应用
2. 进入「新增数据」页面
3. 选择「添加 URL」或「上传文件」
4. 等待：采集 → 归档 → 解析 → 抽取
5. 在「复核中心」审核结果
6. 点击「确认」发布到数据库

### Step 4: 验证结果
```sql
-- 检查已采集的发电量数据
SELECT entity_id, period_label, generation_gwh, confidence_level
FROM generation_records
WHERE entity_id IN (
  'GEM-G100000601208',  -- 三峡
  'GEM-G100000600596',  -- 白鹤滩
  'GEM-G100000604112'   -- Itaipu
)
ORDER BY period_label DESC;
```

---

## 四、数据质量标准

### 必需字段
- ✅ `entity_id`: 水电站唯一标识
- ✅ `period_label`: 年份 (如 "2024")
- ✅ `generation_gwh`: 发电量（吉瓦时）
- ✅ `evidence_id`: 证据文档 ID

### 可选字段
- `value_raw`: 原始数值（如 "103 billion kWh"）
- `unit_raw`: 原始单位
- `confidence_level`: 置信度（高/中/低）
- `extraction_warnings`: 警告信息

### 验证规则
1. **数值合理性**: 发电量不应超过装机容量理论上限
   - 公式: `generation_gwh <= capacity_mw * 8760 / 1000`
   
2. **单位一致性**: 必须转换为 GWh
   - 1 TWh = 1,000 GWh
   - 1 billion kWh = 1 GWh

3. **证据完整性**: 必须有可追溯的原始文档

---

## 五、已知数据源汇总

### 官方政府网站
- 🇨🇳 中国国资委: http://en.sasac.gov.cn/
- 🇺🇸 美国EIA: https://www.eia.gov/electricity/data/detail-data.php
- 🇺🇸 美国USBR: https://www.usbr.gov/

### 公司官网
- 三峡集团: https://www.ctg.com.cn/
- Itaipu Binacional: https://www.itaipu.gov.py/
- RusHydro: https://www.rushydro.ru/
- Hydro-Québec: https://www.hydroquebec.com/

### 第三方数据集
- ORNL Hydrosource: https://hydrosource.ornl.gov/
- GEM Hydropower Tracker: https://globalenergymonitor.org/projects/global-hydropower-tracker/

---

## 六、下一步行动（优先级排序）

### 🔥 高优先级（本周完成）
1. **测试完整流程**: 手动采集三峡大坝 2024 年数据
2. **扩展到 Top 10**: 采集中国前5 + 国际前5
3. **验证数据质量**: 检查抽取准确率

### 📊 中优先级（下周完成）
4. **批量导入美国数据**: 下载 EIA-923，写导入脚本
5. **补充其他国家**: 巴西、俄罗斯、加拿大主要电站

### 🔧 低优先级（后续迭代）
6. **开发自动化爬虫**: 为常见数据源写解析器
7. **定时任务**: 每月自动更新数据
8. **数据校验**: 异常值检测、历史对比

---

## 七、技术实现笔记

### 使用桌面应用 API
```python
from hydro_platform.app.api import Api

api = Api(data_mode="production")
api.initialize()

# 方式1: 添加 URL
result = api.process_url(
    url="http://en.sasac.gov.cn/2025/09/09/c_19816.htm",
    entity_id="GEM-G100000601208",
    source_id="SASAC_NEWS_2025_09_09"
)

# 方式2: 上传文件
result = api.process_file(
    file_path="./downloads/three_gorges_2024.pdf",
    entity_id="GEM-G100000601208",
    source_id="TGD_ANNUAL_REPORT_2024"
)
```

### 批量创建任务
```python
from hydro_platform.tasking.manager import TaskManager
from hydro_platform.models.task import Task
from hydro_platform.common.enums import EntityType, TaskType

tm = TaskManager(conn)
for station in priority_stations:
    task = Task(
        task_id=f"task::{station['entity_id']}::2024",
        entity_id=station['entity_id'],
        entity_type=EntityType.STATION,
        task_type=TaskType.STATION_GENERATION,
        target_period="2024",
        source_hint=station['source_url']
    )
    tm.create_task(task)
```

---

## 八、参考资源

### 已验证的数据源
- [Three Gorges Dam 1.8 Trillion kWh](http://en.sasac.gov.cn/2025/09/09/c_19816.htm)
- [Baihetan 100 Billion kWh](http://en.sasac.gov.cn/2023/10/17/c_16059.htm)
- [World's Largest Clean Energy Corridor 2024](http://en.sasac.gov.cn/2025/01/20/c_18736.htm)
- [Itaipu 2025 Generation](https://www.itaipu.gov.py/noticias/energia/itaipu-suministro-25-768-gwh-de-energia-electrica-a-paraguay-en-el-2025)
- [EIA Detailed Data Files](https://www.eia.gov/electricity/data/detail-data.php)
- [ORNL Hydropower Database](https://hydrosource.ornl.gov/data/datasets/eha-net-generation-plant-database-2003-2024/)

### 记忆文档参考
- [[pipeline-e2e-verified]] - 流水线验证记录
- [[eia923-review-workflow]] - EIA-923 人工复核流程
- [[eia860-capacity-backfill]] - 容量数据补全记录

---

**最后更新**: 2026-09-06  
**维护者**: Claude (Sonnet 5)
