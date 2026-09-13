# 全球水电数据平台 — 网站设计规范

## 一、设计理念

**定位**：专业的数据管理工具产品页，而非营销型官网  
**调性**：工业严谨、数据密集、操作直接  
**视觉策略**：深色主题 + 电光强调 + 清晰信息层级

---

## 二、色彩系统

### 基础色板

```css
/* 深色背景层次 */
--navy: #0F172A;           /* 页面底色 */
--slate: #1E293B;          /* 卡片/区块背景 */
--slate-light: #334155;    /* 悬停/次级元素 */
--slate-border: #475569;   /* 边框/分割线 */

/* 文字层次 */
--text: #F8FAFC;           /* 主文字 */
--text-muted: #94A3B8;     /* 辅助文字/说明 */

/* 功能色 */
--cyan: #22D3EE;           /* 主强调/链接/徽章 */
--orange: #F97316;         /* 行动按钮/重要状态 */
--blue: #38BDF8;           /* 图表/数据可视化 */
--green: #4FD1C5;          /* 成功/正向指标 */
```

### 使用原则

- **主色（cyan）**：导航高亮、链接、工作流徽章、图表主色
- **行动色（orange）**：主要 CTA 按钮、下载按钮
- **辅助色（blue/green）**：KPI 卡片图标、统计数值渐变
- **避免**：紫色渐变、粉色、亮黄色（不符合工业数据产品调性）

---

## 三、排版系统

### 字体族

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
```

**备选方案**（需单独引入）：Sora, IBM Plex Sans, Neue Haas Grotesk

### 字号层级

| 用途 | 字号 | 行高 | 字重 |
|------|------|------|------|
| 页面标题 | 42px | 1.1 | 700 |
| 英雄区标题 | 52px | 1.1 | 700 |
| 卡片标题 | 20px | 1.3 | 600 |
| 正文 | 15-17px | 1.6-1.7 | 400 |
| 辅助文字 | 12-13px | 1.5 | 400 |
| KPI 数值 | 32-48px | 1 | 700 |

### 字距与细节

- 大标题：`letter-spacing: -0.02em`（紧凑现代感）
- 正文：默认字距
- 全大写标签：`letter-spacing: 0.05em`（提升可读性）

---

## 四、布局系统

### 容器尺寸

```css
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}
```

### 网格系统

**三栏布局**（功能卡片、统计卡片）：
```css
.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
}
```

**二栏布局**（数据缺口表 + 图表）：
```css
.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 32px;
}
```

### 间距规范

| 用途 | 尺寸 |
|------|------|
| 区块间距 | 80px |
| 卡片内边距 | 32px |
| 表格单元格 | 12px 16px |
| 按钮内边距 | 12px 24px |
| 小组件间距 | 8-16px |

---

## 五、组件库

### 5.1 导航栏

**结构**：固定顶部 + 毛玻璃背景 + 细边框

```css
position: fixed;
background: rgba(15, 23, 42, 0.8);
backdrop-filter: blur(12px);
border-bottom: 1px solid var(--slate-border);
height: 64px;
```

**交互**：
- 链接悬停：颜色变为 `--cyan`
- 平滑过渡：`transition: color 0.2s`

### 5.2 按钮

**主按钮**（橙色 CTA）：
```css
.btn-primary {
  background: var(--cyan);
  color: var(--navy);
  padding: 12px 24px;
  border-radius: 8px;
}
.btn-primary:hover {
  background: #0EA5E9;
  transform: translateY(-2px);
  box-shadow: 0 12px 24px rgba(34, 211, 238, 0.3);
}
```

**次要按钮**（边框样式）：
```css
.btn-outline {
  background: transparent;
  border: 1px solid var(--slate-border);
}
.btn-outline:hover {
  background: var(--slate);
  border-color: var(--cyan);
}
```

### 5.3 卡片

**基础卡片**：
```css
.card {
  background: var(--card-bg);
  border: 1px solid var(--slate-border);
  border-radius: 16px;
  padding: 32px;
}
```

**功能卡片**（带悬停效果）：
```css
.feature-card:hover {
  border-color: var(--cyan);
  transform: translateY(-4px);
  box-shadow: 0 12px 32px rgba(34, 211, 238, 0.15);
}
```

### 5.4 徽章

**工作流徽章**：
```css
.badge {
  display: inline-block;
  padding: 6px 14px;
  background: rgba(34, 211, 238, 0.1);
  border: 1px solid rgba(34, 211, 238, 0.3);
  border-radius: 20px;
  font-size: 13px;
  color: var(--cyan);
}
```

**功能标签**：
```css
.feature-tags span {
  padding: 4px 10px;
  background: rgba(34, 211, 238, 0.08);
  border: 1px solid rgba(34, 211, 238, 0.2);
  border-radius: 4px;
  font-size: 12px;
}
```

### 5.5 统计数值

**大号数值**（KPI 展示）：
```css
.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--cyan);
  line-height: 1;
}
```

**渐变数值**（强调展示）：
```css
.stat-big {
  font-size: 48px;
  font-weight: 700;
  background: linear-gradient(135deg, var(--cyan), var(--blue));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

### 5.6 图标

**尺寸规范**：
- 导航 logo：28×28px
- 功能卡片图标：48×48px（圆角背景）
- 统计卡片图标：56×56px（圆角背景）
- 行内图标：16-20px

**样式**：
```css
stroke: currentColor;
fill: none;
stroke-width: 2;
```

---

## 六、模块设计

### 6.1 英雄区（Hero Section）

**布局**：左右分栏（1:1.2 比例），左侧内容 + 右侧应用预览

**视觉增强**：
```css
.hero::before {
  content: '';
  position: absolute;
  background: radial-gradient(ellipse at top, rgba(34, 211, 238, 0.15), transparent 50%);
}
```

**关键元素**：
1. 工作流徽章（顶部）
2. 大标题（52px）
3. 描述段落（17px，灰色）
4. 双按钮组（主 + 次）
5. 三项统计数据

### 6.2 应用框架预览

**结构**：
- 顶部标题栏（40px，带圆点装饰）
- 左侧边栏（180px，深色背景）
- 主内容区（KPI 卡片 + 图表占位）

**目的**：展示产品实际界面，而非抽象示意图

### 6.3 功能卡片网格

**布局**：3 列网格，每卡片包含：
1. 图标（48px，青色背景圆角）
2. 标题（20px，粗体）
3. 描述段落（15px，灰色）
4. 功能标签组（小徽章）

**悬停效果**：
- 上移 4px
- 边框变青色
- 投影增强

### 6.4 工作流步骤

**桌面布局**：5 个步骤横向排列，用箭头连接

**移动布局**：竖向堆叠，移除箭头

**视觉编号**：
```css
.step-num {
  position: absolute;
  top: 12px;
  left: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
```

### 6.5 统计数据展示

**三卡布局**：
- 大号渐变数值（48px）
- 标签说明（18px）
- 细节文字（14px，灰色）

**图标**：56px 圆角容器，带半透明彩色背景

---

## 七、响应式设计

### 断点

```css
@media (max-width: 968px) {
  /* 平板/手机 */
}
```

### 关键调整

**导航栏**：保持固定，可能需要汉堡菜单（当前未实现）

**英雄区**：
- 从 2 栏变 1 栏
- 标题从 52px 降至 40px
- 应用预览宽度调整为 100%

**功能卡片**：从 3 栏变 1 栏

**工作流步骤**：
- 从横向变竖向
- 箭头隐藏
- 圆角调整（顶部第一个、底部最后一个）

**统计卡片**：从 3 栏变 1 栏

**下载卡片**：从 2 栏变 1 栏

---

## 八、交互细节

### 微动效

**按钮悬停**：
```css
transition: all 0.2s;
transform: translateY(-2px);
```

**卡片悬停**：
```css
transition: all 0.3s;
transform: translateY(-4px);
```

### 链接状态

- 默认：`--text-muted`
- 悬停：`--cyan`
- 平滑过渡：0.2s

### 避免过度动效

- **不使用**：页面加载动画、弹跳效果、旋转
- **保留**：简洁的位移、颜色过渡、阴影变化

---

## 九、图表占位规范

### 当前实现

使用 CSS 生成简单波形占位：
```css
.chart-placeholder::after {
  background: linear-gradient(to top, rgba(34, 211, 238, 0.3), transparent);
  clip-path: polygon(0 100%, 10% 60%, 30% 70%, 50% 40%, 70% 50%, 90% 20%, 100% 30%, 100% 100%);
}
```

### 生产环境建议

集成 **ECharts**（已在桌面应用中使用）：
- 深色主题：`theme: 'dark'`
- 主色：`--cyan`
- 网格线：`--slate-border`
- 坐标轴文字：`--text-muted`

---

## 十、文件结构

```
docs/website/
├── index.html          # 主页面
├── styles.css          # 样式表
├── design-spec.md      # 本文档
└── assets/             # 图片/字体（未来）
```

---

## 十一、浏览器兼容

**目标浏览器**：
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

**关键 CSS 特性**：
- `backdrop-filter`（毛玻璃导航栏）
- CSS Grid
- CSS 自定义属性（CSS Variables）
- `clip-path`（图表占位）

**回退策略**：
- 不支持 backdrop-filter 的浏览器：使用纯色半透明背景
- 不支持 Grid 的浏览器：降级为 Flexbox

---

## 十二、性能优化

### 已实施

1. **系统字体**：使用 Inter 的 Google Fonts CDN 预连接
2. **内联 SVG**：图标直接嵌入 HTML，减少请求
3. **CSS 变量**：避免重复定义颜色值

### 未来改进

1. **字体子集化**：只加载中文 + 英文 + 数字
2. **图片优化**：应用预览改用实际截图（WebP 格式）
3. **CSS 压缩**：生产环境压缩 CSS
4. **惰性加载**：图表库按需加载

---

## 十三、品牌元素

### Logo 设计

**当前**：SVG 线性图标（水电站建筑抽象形）

**配色**：
- 图标：`stroke: var(--cyan)`
- 文字：`--text`

**尺寸**：
- 导航栏：28×28px
- 页脚：24×24px

### 标语

> 采集 → 归档 → 解析 → 抽取 → 复核 → 发布

**作用**：工作流可视化，贯穿整个产品

---

## 十四、设计交付

### 设计稿

- **工具**：Figma / Sketch / 直接编码
- **输出**：本项目为代码优先，无单独设计稿

### 组件库

当前为静态页面，未来若扩展为多页应用，考虑提取：
- `components/Button.vue`
- `components/Card.vue`
- `components/StatCard.vue`

### 设计令牌（Design Tokens）

可导出为 JSON：
```json
{
  "color": {
    "navy": "#0F172A",
    "cyan": "#22D3EE",
    ...
  },
  "spacing": {
    "xs": "8px",
    "sm": "16px",
    "md": "24px",
    "lg": "32px",
    "xl": "80px"
  },
  "radius": {
    "sm": "4px",
    "md": "8px",
    "lg": "16px",
    "full": "9999px"
  }
}
```

---

## 十五、维护指南

### 修改颜色

所有颜色集中在 `:root` 中定义，修改一处即可全局生效。

### 新增卡片

复制 `.feature-card` 结构，保持：
- 图标 48×48px
- 标题 20px
- 描述 15px
- 标签 12px

### 调整布局

Grid 列数通过媒体查询控制，修改 `grid-template-columns` 即可。

### 更新数据

统计数值（4,965 座水电站、2,058 个项目）需要手动更新 HTML。

---

## 十六、参考资源

- **字体**：[Google Fonts - Inter](https://fonts.google.com/specimen/Inter)
- **图标**：当前使用 SVG 手绘，未来可考虑 [Lucide Icons](https://lucide.dev/)
- **色板工具**：[Coolors](https://coolors.co/)
- **渐变生成**：[CSS Gradient](https://cssgradient.io/)

---

**文档版本**：v1.0  
**最后更新**：2026-09-06  
**设计师/开发者**：Claude (Sonnet 5)
