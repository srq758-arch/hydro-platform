# M3 GUI功能增强计划

**开始时间**: 2026-09-07  
**预计工期**: 4-6小时  
**前置条件**: M2完成（Pipeline架构验证通过）

---

## 执行摘要

M2已验证核心Pipeline架构正常工作。M3专注于GUI用户体验优化，确保所有页面功能完整、易用。

**当前GUI状态**:
- ✅ 已有16个页面路由
- ✅ 基础功能实现（Dashboard、Station列表、数据浏览等）
- ⚠️  部分页面需要功能增强

**M3目标**: 
1. 增强"新增数据"页面（批量导入、验证反馈）
2. 完善"复核中心"页面（详情查看、批量操作）
3. 增强"图表分析"页面（可视化图表）
4. 完善"设置"页面（LLM配置、系统设置）

---

## 当前页面清单

### ✅ 已完整实现
1. **Dashboard（工作台）** - KPI卡片、快捷入口、任务概览
2. **Stations（水电站）** - 列表、搜索、筛选、分页
3. **Station Detail（详情）** - 基本信息、发电量图表
4. **Data Gaps（数据缺口）** - 缺口检测、任务创建
5. **Browse（数据浏览）** - 记录列表、筛选
6. **Top100（排行榜）** - 年度排名
7. **Sources（来源管理）** - 来源列表
8. **Documents（文档资料）** - 文档列表
9. **Evidence（证据中心）** - 证据列表
10. **Projects（项目）** - 项目列表
11. **Tasks（任务）** - 任务列表、状态筛选
12. **Test Lab（测试实验室）** - 测试环境切换

### ⚠️  需要增强
13. **Add Data（新增数据）** - 当前只有单条手动录入
14. **Review（复核中心）** - 当前只有列表，缺详情查看
15. **Stats（统计分析）** - 当前只有基础表格
16. **Settings（设置）** - 当前功能不完整

---

## M3.1: 新增数据页面增强 (1.5小时)

### 当前功能
- ✅ 手动单条录入
- ✅ 基础验证（必填项检查）
- ✅ 提交成功反馈

### 增强目标
1. **批量导入功能**
   - CSV文件上传
   - 模板下载
   - 批量验证
   - 导入进度显示
   - 错误报告

2. **高级验证反馈**
   - 实时字段验证
   - 范围检查提示
   - 重复数据警告
   - 历史数据对比

3. **快捷操作**
   - 从数据缺口一键创建
   - 历史数据复制
   - 常用电站收藏

### 实施步骤
```
Step 1: 添加CSV导入UI组件 (30分钟)
  - 文件上传组件
  - 拖拽上传支持
  - 模板下载链接

Step 2: 实现批量导入后端API (30分钟)
  - parse_csv() 函数
  - validate_batch() 函数
  - bulk_create_records() 函数

Step 3: 增强验证反馈UI (30分钟)
  - 实时验证提示
  - 错误高亮
  - 验证进度条
```

---

## M3.2: 复核中心页面完善 (1.5小时)

### 当前功能
- ✅ 复核列表
- ✅ 批量通过/拒绝
- ✅ 状态筛选

### 增强目标
1. **详情查看对话框**
   - 完整数据展示
   - 来源证据链接
   - 置信度详情
   - 历史版本对比

2. **审核辅助**
   - 相似数据对比
   - 趋势异常提示
   - 置信度解释
   - 快捷审核理由

3. **审核历史**
   - 审核记录追踪
   - 审核员标签
   - 审核统计

### 实施步骤
```
Step 1: 实现详情对话框 (40分钟)
  - 模态框组件
  - 数据详情展示
  - 证据链接跳转

Step 2: 添加审核辅助功能 (30分钟)
  - 相似数据查询API
  - 趋势分析提示
  - 快捷理由模板

Step 3: 审核历史功能 (20分钟)
  - 审核记录列表
  - 筛选和搜索
```

---

## M3.3: 统计分析页面增强 (1.5小时)

### 当前功能
- ✅ 基础数据表格
- ✅ 简单统计信息

### 增强目标
1. **可视化图表**
   - 年度发电量趋势图
   - 国家对比柱状图
   - 数据覆盖率饼图
   - Top电站排名图

2. **交互式筛选**
   - 年份范围选择
   - 国家多选
   - 容量范围筛选
   - 实时图表更新

3. **导出功能**
   - 图表导出为PNG
   - 数据导出为CSV/Excel
   - 报告生成

### 实施步骤
```
Step 1: 集成图表库 (30分钟)
  - 选择Chart.js或ECharts
  - 基础配置
  - 主题适配

Step 2: 实现核心图表 (40分钟)
  - 趋势图组件
  - 对比图组件
  - 饼图组件

Step 3: 添加交互和导出 (20分钟)
  - 筛选器联动
  - 图表导出功能
```

---

## M3.4: 设置页面完善 (1.5小时)

### 当前功能
- ✅ 系统信息显示
- ⚠️  LLM配置界面（不完整）

### 增强目标
1. **LLM配置管理**
   - DeepSeek配置
   - API Key管理
   - 连接测试
   - 使用统计

2. **系统设置**
   - 数据库管理
     - 备份
     - 还原
     - 重建索引
   - 缓存清理
   - 日志查看

3. **用户偏好**
   - 语言设置
   - 主题切换（明/暗）
   - 默认筛选器
   - 通知设置

### 实施步骤
```
Step 1: LLM配置界面 (40分钟)
  - 配置表单
  - API Key输入（密码遮罩）
  - 连接测试按钮
  - 使用统计图表

Step 2: 数据库管理功能 (30分钟)
  - 备份导出
  - 一键重建索引
  - 清理临时数据

Step 3: 用户偏好设置 (20分钟)
  - 主题切换开关
  - 语言选择器
  - 偏好保存到localStorage
```

---

## 技术实施细节

### 前端技术栈
- **无框架原生JS** (当前实现)
- **图表库**: Chart.js (轻量、易用)
- **UI组件**: 自定义CSS + 原生HTML5
- **状态管理**: 全局appState对象

### 后端API新增
```python
# api.py 新增方法

# M3.1: 批量导入
def parse_csv_upload(file_content: str) -> dict
def validate_batch_records(records: list) -> dict
def bulk_create_records(records: list) -> dict

# M3.2: 复核详情
def get_review_detail_enhanced(record_id: int) -> dict
def get_similar_records(entity_id: str, year: str, value: float) -> list
def get_review_history(record_id: int) -> list

# M3.3: 统计分析
def get_generation_trend(entity_ids: list, year_range: tuple) -> dict
def get_country_comparison(countries: list, year: str) -> dict
def get_coverage_stats_detailed() -> dict

# M3.4: 设置管理
def backup_database() -> str
def restore_database(backup_file: str) -> dict
def clear_cache() -> dict
def get_llm_usage_stats() -> dict
```

### 前端新增组件
```javascript
// 通用组件
function Modal(content, options) - 模态对话框
function FileUpload(accept, onUpload) - 文件上传
function Chart(type, data, options) - 图表包装
function Toast(message, type) - 提示消息

// M3.1组件
function renderBatchImportDialog()
function renderValidationReport(errors)

// M3.2组件
function renderReviewDetailModal(recordId)
function renderSimilarRecordsPanel(records)

// M3.3组件
function renderTrendChart(data)
function renderComparisonChart(data)

// M3.4组件
function renderLLMConfigForm()
function renderThemeToggle()
```

---

## 验收标准

### M3.1: 新增数据
- [ ] 可以上传CSV文件批量导入
- [ ] 导入前有完整验证，显示错误详情
- [ ] 导入进度实时显示
- [ ] 导入结果有成功/失败统计
- [ ] 模板可下载

### M3.2: 复核中心
- [ ] 点击记录打开详情对话框
- [ ] 详情显示完整数据+证据链接
- [ ] 可以查看相似历史数据
- [ ] 审核理由可选快捷模板
- [ ] 审核历史可追溯

### M3.3: 统计分析
- [ ] 显示3种以上可视化图表
- [ ] 图表可交互（筛选、缩放）
- [ ] 图表可导出为PNG
- [ ] 数据可导出为CSV

### M3.4: 设置
- [ ] LLM配置可保存和测试
- [ ] 数据库可一键备份
- [ ] 主题可切换（明/暗）
- [ ] 设置保存后刷新仍保留

---

## 时间安排

| 任务 | 预计时间 | 优先级 |
|-----|---------|--------|
| M3.1: 新增数据增强 | 1.5小时 | P1 |
| M3.2: 复核中心完善 | 1.5小时 | P0 |
| M3.3: 统计分析增强 | 1.5小时 | P2 |
| M3.4: 设置页面完善 | 1.5小时 | P1 |
| **总计** | **6小时** | |

---

## 依赖项

### 外部库（可选）
- **Chart.js** (v4.x) - MIT License, 60KB gzipped
  - 或使用原生Canvas API（更轻量但开发时间长）

### 无需新增依赖
- 文件上传：HTML5 File API
- CSV解析：原生JS `split()`
- 模态框：原生HTML + CSS
- 主题切换：CSS变量 + localStorage

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| CSV解析复杂度高 | 中 | 限制CSV格式，提供严格模板 |
| 图表库体积大 | 低 | 使用CDN加载，延迟加载 |
| 批量导入性能 | 中 | 限制单次500条，显示进度 |
| 浏览器兼容性 | 低 | 仅支持现代浏览器（Chrome/Edge/Firefox） |

---

## 下一步（M4）

M3完成后的下一步选项：

**M4A: 批量任务管理** (3-4小时)
- Seed List管理（CSV上传100个电站）
- 批量任务创建
- 批量监控Dashboard
- 批量结果导出

**M4B: 生产部署优化** (2-3小时)
- Docker容器化
- 数据库迁移工具
- 性能监控
- 错误追踪

**M4C: 高级功能** (4-6小时)
- 数据版本控制
- 审核工作流
- 用户权限管理
- API限流保护

---

**创建时间**: 2026-09-07  
**最后更新**: 2026-09-07  
**状态**: 待开始
