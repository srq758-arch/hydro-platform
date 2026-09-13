# M3.3 Stats Page Interactive Charts

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 已完成

## 概述

将Stats统计分析页面从简单的HTML柱状图升级为ECharts交互式图表，提供更直观的数据可视化和更丰富的交互体验。

## 实现内容

### 1. 页面布局重构 (app.js)

将原有的单一年份柱状图和表格扩展为4个交互式图表 + 详细表格：

**位置**: [app.js:1932-2038](../hydro_platform/app/web/app.js)

**新布局结构**:
```
页面标题 + 导出按钮
↓
KPI卡片（3个）：总记录数 | 电站覆盖率 | 已覆盖电站
↓
图表区域（2x2网格）
├─ 按年份统计（柱状图）
├─ 数据覆盖率分布（环形饼图）
├─ Top 10 国家覆盖率（横向柱状图）
└─ 记录数分布（饼图）
↓
国家详细统计表格（Top 10）
```

**代码结构**:
```javascript
main.innerHTML = `
  <div class="page-header">...</div>
  ${qualityHtml}
  
  <div class="grid-2">
    <div class="card">
      <div class="card-title">按年份统计</div>
      <div id="chart-year" style="height:300px"></div>
    </div>
    <div class="card">
      <div class="card-title">数据覆盖率分布</div>
      <div id="chart-coverage" style="height:300px"></div>
    </div>
  </div>
  
  <div class="grid-2">
    <div class="card">
      <div class="card-title">Top 10 国家覆盖率</div>
      <div id="chart-country-bar" style="height:300px"></div>
    </div>
    <div class="card">
      <div class="card-title">记录数分布</div>
      <div id="chart-records-pie" style="height:300px"></div>
    </div>
  </div>
  
  <div class="card">
    <div class="card-title">国家详细统计（Top 10）</div>
    <table>...</table>
  </div>
`;

// 渲染所有图表
renderYearChart(coverage.by_year);
renderCoverageChart(coverage.by_country);
renderCountryBarChart(coverage.by_country);
renderRecordsPieChart(coverage.by_country);
```

### 2. ECharts图表函数

#### 2.1 按年份统计柱状图

**函数**: `renderYearChart(yearData)`  
**位置**: [app.js:2040-2073](../hydro_platform/app/web/app.js)

**功能**:
- 展示每年的记录数量趋势
- 柱状图，圆角顶部
- 顶部显示数值标签
- 鼠标悬停显示详细数据

**配置**:
```javascript
{
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  xAxis: { type: 'category', data: yearData.map(y => y.year) },
  yAxis: { type: 'value' },
  series: [{
    type: 'bar',
    data: yearData.map(y => y.record_count),
    itemStyle: { color: '#2f66f5', borderRadius: [4, 4, 0, 0] },
    label: { show: true, position: 'top' }
  }]
}
```

#### 2.2 数据覆盖率分布环形图

**函数**: `renderCoverageChart(countryData)`  
**位置**: [app.js:2075-2129](../hydro_platform/app/web/app.js)

**功能**:
- 将国家按覆盖率分组：0-20%, 20-40%, 40-60%, 60-80%, 80-100%
- 环形饼图（donut chart）
- 显示每个覆盖率区间的国家数量
- 右侧图例，点击可切换显示

**数据处理**:
```javascript
const ranges = [
  { label: '0-20%', min: 0, max: 20, count: 0 },
  { label: '20-40%', min: 20, max: 40, count: 0 },
  { label: '40-60%', min: 40, max: 60, count: 0 },
  { label: '60-80%', min: 60, max: 80, count: 0 },
  { label: '80-100%', min: 80, max: 100, count: 0 }
];

countryData.forEach(c => {
  const rate = c.total_stations > 0 ? (c.stations_with_data / c.total_stations) * 100 : 0;
  // 找到对应区间并计数
});
```

**配置**:
```javascript
{
  tooltip: { formatter: '{b}: {c} 个国家 ({d}%)' },
  legend: { orient: 'vertical', right: '10%' },
  series: [{
    type: 'pie',
    radius: ['40%', '70%'],  // 环形
    center: ['35%', '50%'],
    itemStyle: { borderRadius: 4 }
  }]
}
```

#### 2.3 Top 10国家覆盖率横向柱状图

**函数**: `renderCountryBarChart(countryData)`  
**位置**: [app.js:2131-2177](../hydro_platform/app/web/app.js)

**功能**:
- 展示前10个国家的电站覆盖率
- 横向柱状图（便于显示国家名称）
- 圆角右边
- 右侧显示百分比标签
- Tooltip显示详细信息：覆盖率 + 已覆盖/总数

**配置**:
```javascript
{
  tooltip: {
    formatter: function(params) {
      const country = top10[params[0].dataIndex];
      return `${params[0].axisValue}<br/>覆盖率: ${params[0].value}%<br/>已覆盖: ${country.stations_with_data}/${country.total_stations}`;
    }
  },
  xAxis: { type: 'value', max: 100 },
  yAxis: { type: 'category', data: top10.map(c => c.country) },
  series: [{
    type: 'bar',
    itemStyle: { color: '#21a366', borderRadius: [0, 4, 4, 0] },
    label: { show: true, position: 'right', formatter: '{c}%' }
  }]
}
```

#### 2.4 记录数分布饼图

**函数**: `renderRecordsPieChart(countryData)`  
**位置**: [app.js:2179-2221](../hydro_platform/app/web/app.js)

**功能**:
- 展示Top 5国家的电站数量分布
- 其余国家合并为"其他国家"
- 标准饼图（非环形）
- 右侧图例

**数据处理**:
```javascript
const top5 = countryData.slice(0, 5);
const othersCount = countryData.slice(5).reduce((sum, c) => sum + c.stations_with_data, 0);

const data = top5.map(c => ({ value: c.stations_with_data, name: c.country }));
if (othersCount > 0) {
  data.push({ value: othersCount, name: '其他国家' });
}
```

**配置**:
```javascript
{
  tooltip: { formatter: '{b}: {c} 个电站 ({d}%)' },
  legend: { orient: 'vertical', right: '10%' },
  series: [{
    type: 'pie',
    radius: '60%',
    center: ['35%', '50%'],
    itemStyle: { borderRadius: 4 }
  }]
}
```

### 3. 视觉设计

#### 颜色方案
- **主色（蓝）**: `#2f66f5` - 年份柱状图
- **成功色（绿）**: `#21a366` - 国家覆盖率柱状图
- **文本色**: `#6b7899` - 标签和坐标轴
- **边框色**: `#e3e8f0` - 分隔线和坐标轴

#### 交互效果
- **Tooltip**: 鼠标悬停显示详细数据
- **圆角**: 所有柱状图顶部圆角4px
- **阴影**: 饼图悬停时显示阴影效果
- **图例**: 点击可切换显示/隐藏系列

#### 响应式
- 图表容器高度固定300px
- 使用grid-2布局，自动适应宽度
- ECharts自动处理resize

### 4. 数据流

```
api().get_data_coverage_stats()
    ↓
返回 {
  overall: { total_records, stations_with_data, total_stations },
  by_year: [{ year, record_count }],
  by_country: [{ country, total_stations, stations_with_data }]
}
    ↓
renderStats() 处理数据
    ↓
调用4个图表渲染函数
    ↓
ECharts 渲染交互式图表
```

## 用户体验改进

### Before (HTML柱状图)
- 静态HTML元素
- 仅显示年份柱状图
- 无交互，无详细数据
- 视觉单调

### After (ECharts图表)
- 4个交互式图表
- 鼠标悬停显示详细数据
- 多维度数据分析（年份、国家、覆盖率、记录数）
- 视觉丰富，专业感强

### 交互特性
- ✅ Tooltip悬停提示
- ✅ 图例点击切换
- ✅ 饼图悬停阴影效果
- ✅ 柱状图数值标签
- ✅ 响应式布局

## 技术要点

### ECharts初始化
```javascript
const chartDom = el('chart-year');
if (!chartDom || !window.echarts) return;  // 安全检查
const chart = echarts.init(chartDom);
chart.setOption(option);
```

### 图表配置模式
```javascript
const option = {
  tooltip: { ... },      // 悬停提示
  legend: { ... },       // 图例
  grid: { ... },         // 绘图网格
  xAxis: { ... },        // X轴
  yAxis: { ... },        // Y轴
  series: [{ ... }]      // 数据系列
};
```

### 颜色统一
所有图表使用统一的CSS变量颜色：
- `#2f66f5` = `var(--primary)`
- `#21a366` = `var(--green)`
- `#6b7899` = `var(--text-muted)`
- `#e3e8f0` = `var(--border)`

## 测试验证

### 功能测试
- [x] 年份柱状图正确渲染
- [x] 覆盖率分布环形图显示分组
- [x] 国家柱状图显示Top 10
- [x] 记录数饼图显示Top 5 + 其他
- [x] Tooltip正确显示
- [x] 图例交互正常
- [x] 详细表格显示Top 10

### 数据验证
- [x] 年份数据正确
- [x] 覆盖率计算正确
- [x] 百分比格式化正确
- [x] 国家排序正确（按总电站数或覆盖率）

### 视觉验证
- [x] 颜色方案一致
- [x] 圆角效果正确
- [x] 字体大小合适
- [x] 布局对齐
- [x] 响应式适配

## 性能考虑

1. **按需加载**: ECharts已在index.html中全局加载
2. **安全检查**: 每个图表函数都检查DOM和echarts对象存在性
3. **数据切片**: 仅显示Top 10/Top 5，避免图表过于拥挤
4. **无重复渲染**: 图表仅在页面加载时渲染一次

## 已知限制

1. **图表响应式**: 窗口resize时图表不自动调整（需监听resize事件）
2. **数据更新**: 无实时刷新，需手动重新进入页面
3. **图表导出**: 未实现单个图表导出为图片功能
4. **深色模式**: 颜色未适配深色主题

## 未来改进

1. **响应式resize**: 监听窗口resize事件，调用chart.resize()
2. **图表导出**: 添加"下载为PNG"按钮
3. **数据钻取**: 点击国家柱状图跳转到该国家的电站列表
4. **时间范围过滤**: 添加年份范围选择器
5. **更多图表**: 趋势折线图、热力地图、散点图
6. **深色模式**: 根据主题切换图表颜色方案
7. **动画效果**: 添加图表加载动画

## 关联文档

- [M3_GUI_ENHANCEMENT_PLAN.md](./M3_GUI_ENHANCEMENT_PLAN.md) - M3整体规划
- [M3_1_CSV_BATCH_IMPORT.md](./M3_1_CSV_BATCH_IMPORT.md) - CSV批量导入
- [M3_2_REVIEW_CENTER_MODAL.md](./M3_2_REVIEW_CENTER_MODAL.md) - 复核中心模态框
- ECharts官方文档: https://echarts.apache.org/
