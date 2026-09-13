# DeepSeek Discovery Level 3 使用指南

## 一、功能说明

DeepSeek Discovery Level 3 是智能数据来源发现的增强功能，使用DeepSeek AI的能力：

### 两阶段策略

**阶段1: 智能推理**
- DeepSeek根据电站信息推理可能的URL模式
- 不联网，纯推理
- 速度快，适合生成候选URL

**阶段2: 联网搜索**
- DeepSeek使用联网搜索能力
- 查找真实存在的文档
- 返回可访问的URL

### 优势

- ✅ 理解中文电站名称
- ✅ 智能推理URL模式
- ✅ 联网验证真实性
- ✅ 自动去重和排序
- ✅ 与Level 1-2无缝集成

---

## 二、配置步骤

### 1. 获取DeepSeek API Key

访问 https://platform.deepseek.com/ 注册并获取API Key

### 2. 设置环境变量

**Windows:**
```bash
set DEEPSEEK_API_KEY=your_api_key_here
```

**Linux/Mac:**
```bash
export DEEPSEEK_API_KEY=your_api_key_here
```

### 3. 验证配置

```bash
# 测试DeepSeek功能
cd F:\hydro_platform_v1
python tests/manual/test_deepseek_discovery.py
```

---

## 三、使用方法

### 方法1: 直接使用DeepSeekSourceFinder

```python
from hydro_platform.discovery.deepseek_search import DeepSeekSourceFinder

# 创建Finder（自动从环境变量读取API Key）
finder = DeepSeekSourceFinder()

# 或手动指定API Key
finder = DeepSeekSourceFinder(api_key="your_api_key")

# 检查是否启用
if finder.enabled:
    # 构造任务
    task = {
        "entity_name": "三峡大坝",
        "target_period": "2024",
        "metric": "generation",
        "country": "China"
    }
    
    # 搜索
    candidates = finder.find(task, max_candidates=5)
    
    # 查看结果
    for candidate in candidates:
        print(f"URL: {candidate['url']}")
        print(f"类型: {candidate['source_type']}")
        print(f"方法: {candidate['discovery_method']}")
```

---

### 方法2: 通过DiscoveryResolver（推荐）

```python
from hydro_platform.database.connection import connect
from hydro_platform.discovery.resolver import DiscoveryResolver
from pathlib import Path

# 连接数据库
db_path = Path("data/hydropower.sqlite")
conn = connect(db_path)

# 创建Resolver（传入API Key）
resolver = DiscoveryResolver(conn, deepseek_api_key="your_api_key")
# 或自动从环境变量读取
resolver = DiscoveryResolver(conn)

# 执行Discovery（自动使用Level 1-2-3）
task = {
    "entity_id": "CHN_some_station",
    "entity_name": "某水电站",
    "target_period": "2024",
    "metric": "generation"
}

candidates = resolver.discover(task, min_candidates=3, max_candidates=10)

# Level 1-2找不到足够候选时，自动触发Level 3
```

---

### 方法3: 在Pipeline中自动使用

Pipeline已经集成DiscoveryResolver，设置API Key后自动启用：

```python
# 设置环境变量
import os
os.environ["DEEPSEEK_API_KEY"] = "your_api_key"

# 正常运行Pipeline
# 当Level 1-2候选不足时，会自动调用Level 3
```

---

## 四、工作流程

```
用户发起任务
  ↓
Level 1: 官方来源 (OfficialSourceFinder)
  ↓ 候选不足
Level 2: 权威机构 (AuthoritySourceFinder)
  ↓ 候选仍不足
Level 3: DeepSeek智能搜索 ← 新增
  ├─ 阶段1: 智能推理URL
  └─ 阶段2: 联网搜索验证
  ↓
ReliabilityScorer 统一排序
  ↓
返回Top N候选
```

---

## 五、API参考

### DeepSeekSourceFinder

#### `__init__(api_key=None)`
初始化Finder

**参数:**
- `api_key` (str, 可选): API密钥，不提供则从环境变量读取

**属性:**
- `enabled` (bool): 是否启用（有API Key则为True）

---

#### `find(task, max_candidates=5)`
发现候选来源

**参数:**
- `task` (dict): 任务字典
  - `entity_name`: 电站名称
  - `target_period`: 目标年份
  - `metric`: 指标（generation/capacity）
  - `country`: 国家（可选）
- `max_candidates` (int): 最多返回候选数

**返回:**
- `List[dict]`: 候选列表

**候选格式:**
```python
{
    "url": "https://example.com/report.pdf",
    "source_type": "official/authority/deepseek_search",
    "document_type": "pdf/html/excel",
    "title": "文档标题",
    "discovery_method": "reasoning/web_search",
    "metadata": {
        "reasoning": "选择理由",
        "from_deepseek": True
    }
}
```

---

### DiscoveryResolver（更新）

#### `__init__(conn, deepseek_api_key=None)`
初始化Resolver

**新参数:**
- `deepseek_api_key` (str, 可选): DeepSeek API密钥

---

## 六、配置说明

### Level 3触发条件

Level 3只在以下情况触发：

1. Level 1 + Level 2 找到的候选数 < `min_candidates`
2. 环境变量设置了 `DEEPSEEK_API_KEY`

### 参数调整

```python
# 设置min_candidates=8，更容易触发Level 3
candidates = resolver.discover(
    task,
    min_candidates=8,   # 提高阈值
    max_candidates=10
)

# 如果Level 1-2只找到3个，会触发Level 3继续查找
```

---

## 七、测试验证

### 运行测试脚本

```bash
cd F:\hydro_platform_v1
python tests/manual/test_deepseek_discovery.py
```

### 测试内容

1. **测试1: DeepSeek Finder基础功能**
   - 验证API Key
   - 测试智能搜索
   - 检查返回格式

2. **测试2: Discovery完整集成**
   - Level 1-2-3协同
   - 统计各级别贡献
   - 验证排序

3. **测试3: 真实电站场景**
   - 查询真实数据库
   - 无官方网站的电站
   - 验证实际效果

### 预期结果

```
[OK] DeepSeek Finder
[OK] Discovery集成
[OK] 真实电站场景

通过率: 3/3 (100.0%)
```

---

## 八、成本说明

### DeepSeek API价格

- **推理阶段**: ~0.001元/次（不联网）
- **搜索阶段**: ~0.003元/次（联网）
- **单次完整搜索**: ~0.004元

### 成本优化建议

1. **提高Level 1-2质量**
   - 补全stations表的official_website
   - 减少Level 3触发频率

2. **缓存搜索结果**
   - 将DeepSeek返回的URL注册到SourceRegistry
   - 下次直接使用历史源

3. **按需启用**
   - 只在必要时设置API Key
   - Level 1-2通常已足够

---

## 九、故障排查

### 问题1: Level 3未触发

**检查清单:**
```python
# 1. API Key是否设置
import os
print(os.environ.get("DEEPSEEK_API_KEY"))

# 2. Finder是否启用
from hydro_platform.discovery.deepseek_search import DeepSeekSourceFinder
finder = DeepSeekSourceFinder()
print(f"启用状态: {finder.enabled}")

# 3. min_candidates是否过低
# 如果Level 1-2已找到足够候选，不会触发Level 3
```

---

### 问题2: API调用失败

**常见错误:**

```
requests.exceptions.HTTPError: 401 Unauthorized
→ API Key错误或过期

requests.exceptions.Timeout
→ 网络超时，检查网络连接

json.JSONDecodeError
→ DeepSeek返回格式异常，已自动处理
```

**解决方案:**
```python
# 查看详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 然后运行测试
```

---

### 问题3: 返回结果为空

**可能原因:**
1. DeepSeek未找到相关信息
2. 电站名称不准确
3. 搜索关键词不匹配

**优化方法:**
```python
# 提供更多上下文
task = {
    "entity_name": "三峡大坝",  # 中文名
    "entity_name_en": "Three Gorges Dam",  # 英文名
    "operator": "中国三峡集团",  # 运营商
    "country": "China",
    "target_period": "2024",
    "metric": "generation"
}
```

---

## 十、最佳实践

### 1. 分级使用策略

```python
# 优先级策略
if has_official_website:
    # Level 1足够
    candidates = level1_only()
elif is_major_station:
    # Level 1-2
    candidates = level1_and_level2()
else:
    # Level 1-2-3全用
    candidates = full_discovery()
```

### 2. 结果验证

```python
# DeepSeek返回的URL需要验证
import requests

for candidate in candidates:
    try:
        response = requests.head(candidate['url'], timeout=5)
        if response.status_code == 200:
            print(f"✓ {candidate['url']}")
        else:
            print(f"✗ {candidate['url']} (HTTP {response.status_code})")
    except:
        print(f"✗ {candidate['url']} (无法访问)")
```

### 3. 持久化搜索结果

```python
# 找到可用URL后立即注册
from hydro_platform.registry.source_registry import SourceRegistry

registry = SourceRegistry(conn)

for candidate in candidates:
    if is_valid_url(candidate['url']):
        registry.register_new_source(
            entity_id=task['entity_id'],
            source_url=candidate['url'],
            metadata={
                "source_type": candidate['source_type'],
                "document_type": candidate['document_type'],
                "covered_metric": task['metric'],
                "covered_year": int(task['target_period']),
                "estimated_reliability": 0.7,  # DeepSeek搜索结果初始评分
                "discovery_method": "deepseek_level3"
            }
        )
```

---

## 十一、与其他方案对比

| 方案 | 优点 | 缺点 | 成本 |
|------|------|------|------|
| **DeepSeek** | 中文支持好，联网搜索，智能推理 | 需要API Key | ~0.004元/次 |
| **Google Custom Search** | 搜索质量高 | 需要API Key，中文支持一般 | $5/1000次 |
| **Bing Search API** | 微软官方 | 需要Azure账号 | 付费 |
| **SerpAPI** | 聚合多个搜索引擎 | 贵 | $50/5000次 |

**推荐**: DeepSeek（性价比最高，中文支持最好）

---

## 十二、下一步

1. ✅ DeepSeek Level 3已实现
2. ⏳ GUI集成 TaskScheduler（下一步）
3. ⏳ Ground Truth Benchmark工具

---

**文档版本**: v1.0  
**更新日期**: 2026-09-07  
**作者**: Claude Code
