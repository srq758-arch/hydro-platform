# M3.2 Review Center Modal Implementation

**完成时间**: 2026-09-08  
**优先级**: P0  
**状态**: ✅ 已完成

## 概述

将复核详情页从全页面导航改为模态框（modal dialog）显示，提升用户体验，避免页面跳转打断工作流。

## 实现内容

### 1. 通用模态框组件 (app.js)

新增两个全局函数：

- **showModal(title, content, options)**
  - 创建或更新模态框
  - 支持自定义宽度、footer按钮
  - 自动处理ESC键关闭
  - 支持点击遮罩层关闭
  
- **closeModal()**
  - 移除当前模态框
  - 清理事件监听器

**位置**: [app.js:1980-2030](../hydro_platform/app/web/app.js)

```javascript
function showModal(title, content, options = {}) {
  const modalId = 'app-modal';
  let existing = el(modalId);
  if (existing) existing.remove();
  
  const modal = document.createElement('div');
  modal.id = modalId;
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-container" style="max-width:${options.width || '800px'}">
      <div class="modal-header">
        <div class="modal-title">${esc(title)}</div>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">${content}</div>
      ${options.footer ? `<div class="modal-footer">${options.footer}</div>` : ''}
    </div>
  `;
  document.body.appendChild(modal);
  
  // ESC键关闭
  const escHandler = e => { if (e.key === 'Escape') closeModal(); };
  document.addEventListener('keydown', escHandler);
  modal._escHandler = escHandler;
  
  // 点击遮罩层关闭
  modal.addEventListener('click', e => {
    if (e.target === modal) closeModal();
  });
}
```

### 2. 复核详情模态框 (app.js)

重构 `viewReviewDetail()` 函数：

- 使用 `showModal()` 代替 `renderContent()`
- 900px宽度模态框显示完整信息
- 包含三个操作按钮的footer

**位置**: [app.js:2053-2129](../hydro_platform/app/web/app.js)

**显示内容**:
- 抽取结果卡片（水电站名、年份、发电量、置信度等）
- 来源信息卡片（来源、发布者、URL、页码等）
- 证据摘录（原始文本片段）
- 复核备注区域（支持添加备注）

**Footer按钮**:
```javascript
const footer = `
  <button class="btn btn-outline" onclick="addReviewNote(${d.id})">添加备注</button>
  <button class="btn btn-outline" onclick="rejectRecordFromModal(${d.id})">拒绝</button>
  <button class="btn btn-primary" onclick="approveRecordFromModal(${d.id})">通过复核</button>
`;
```

### 3. 模态框专用操作函数 (app.js)

新增两个wrapper函数处理模态框内的审核操作：

- **approveRecordFromModal(recordId)**
  - 调用 `api().approve_record()`
  - 关闭模态框
  - 刷新复核列表 `renderReview()`
  - 显示成功提示
  
- **rejectRecordFromModal(recordId)**
  - 弹出prompt要求输入拒绝理由
  - 调用 `api().reject_record()`
  - 关闭模态框
  - 刷新列表
  - 显示成功提示

**位置**: [app.js:2165-2186](../hydro_platform/app/web/app.js)

**关键逻辑**:
```javascript
async function approveRecordFromModal(recordId) {
  if (!confirm('确认通过复核？该记录将可用于 Top 100 等榜单。')) return;
  try {
    await api().approve_record(recordId);
    closeModal();           // ← 关闭模态框
    renderReview();         // ← 刷新列表
    alert('已通过复核');
  } catch (e) {
    alert('操作失败：' + e);
  }
}
```

### 4. 模态框样式 (styles.css)

新增模态框CSS样式：

**位置**: [styles.css:244-319](../hydro_platform/app/web/styles.css)

**样式特性**:
- 深色半透明遮罩层 `rgba(26, 39, 68, 0.6)`
- 居中弹出动画（fadeIn + slideUp）
- 白色卡片背景，圆角阴影
- 最大高度90vh，内容区域可滚动
- header固定、body可滚动、footer固定的布局
- 关闭按钮hover效果

```css
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(26, 39, 68, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.2s ease;
}

.modal-container {
  background: var(--card-bg);
  border-radius: var(--radius);
  box-shadow: 0 20px 60px rgba(26, 39, 68, 0.3);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  animation: slideUp 0.3s ease;
}
```

## 用户体验改进

### Before (全页面导航)
1. 点击"查看" → 整个页面内容替换
2. 操作完成 → 需要手动返回列表
3. 上下文丢失 → 看不到列表中的其他记录

### After (模态框)
1. 点击"查看" → 模态框覆盖显示
2. 操作完成 → 模态框自动关闭，列表自动刷新
3. 上下文保留 → 列表始终在背景可见

### 交互方式
- ✅ ESC键关闭
- ✅ 点击遮罩层关闭
- ✅ 点击×按钮关闭
- ✅ 操作完成后自动关闭
- ✅ 流畅动画效果

## 测试验证

### 功能测试
- [x] 模态框正常弹出显示
- [x] 详情数据正确加载
- [x] ESC键关闭
- [x] 点击遮罩层关闭
- [x] 点击×按钮关闭
- [x] "通过复核"按钮 → 调用API → 关闭模态框 → 刷新列表
- [x] "拒绝"按钮 → 输入理由 → 调用API → 关闭模态框 → 刷新列表
- [x] "添加备注"按钮 → 添加备注 → 实时刷新备注区域

### 样式测试
- [x] 900px宽度适中
- [x] 最大高度90vh防止溢出
- [x] 内容区域正确滚动
- [x] 动画流畅自然
- [x] 遮罩层颜色正确
- [x] 关闭按钮hover效果

## 代码质量

### 可复用性
- ✅ `showModal()` 通用组件可用于其他功能
- ✅ CSS样式独立于业务逻辑
- ✅ 事件处理正确清理避免内存泄漏

### 向后兼容
- ✅ 保留原有 `approveRecord()` 和 `rejectRecord()` 函数
- ✅ 其他页面如需全页面导航仍可使用旧函数

## 下一步

M3.2 Review Center 基础功能已完成，建议后续优化：

1. **Toast通知**: 替换 `alert()` 为优雅的toast提示
2. **加载状态**: 操作过程中显示loading spinner
3. **键盘导航**: 支持Tab键在按钮间切换
4. **批量操作**: 支持从列表选中多条记录批量审核

## 关联文档

- [M3_GUI_ENHANCEMENT_PLAN.md](./M3_GUI_ENHANCEMENT_PLAN.md) - M3整体规划
- [M2_3_E2E_COMPLETE.md](./M2_3_E2E_COMPLETE.md) - M2端到端验证
