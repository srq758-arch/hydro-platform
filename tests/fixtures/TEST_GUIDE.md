# 全球水电数据平台 - 测试指南

## 测试文件位置
`F:\hydro_platform_v1\tests\fixtures\`

## 测试用例

### 测试 1：正常文档上传 ✅
**文件：** `test_valid_report.html`  
**预期结果：**
- 成功解析
- 抽取到发电量：88,200 GWh（或 88.2 TWh）
- 显示绿色"成功"徽章
- 保存到数据库

**操作步骤：**
1. 打开应用 → 点击"新增数据"
2. 方式 2：上传本地文件
3. 文件路径：`F:\hydro_platform_v1\tests\fixtures\test_valid_report.html`
4. 来源 ID：`三峡集团`
5. 点击"开始处理"

---

### 测试 2：损坏文件 ❌
**文件：** `corrupt.pdf`  
**预期结果：**
- 解析失败
- 显示红色"PARSE"徽章
- 错误信息："文件解析失败，可能是文件损坏或格式不支持"

**操作步骤：**
1. 新增数据 → 方式 2
2. 文件路径：`F:\hydro_platform_v1\tests\fixtures\corrupt.pdf`
3. 来源 ID：`测试`
4. 点击"开始处理"

---

### 测试 3：无发电量数据 ❌
**文件：** `no_data.html`  
**预期结果：**
- 解析成功
- 抽取失败
- 显示橙色"EXTRACTION"徽章
- 错误信息："文件里没找到发电量数据，可能不是我们需要的报告"

**操作步骤：**
1. 新增数据 → 方式 2
2. 文件路径：`F:\hydro_platform_v1\tests\fixtures\no_data.html`
3. 来源 ID：`测试`
4. 点击"开始处理"

---

### 测试 4：404 错误 ❌
**URL：** `https://example.com/nonexistent_report.pdf`  
**预期结果：**
- 下载失败
- 显示红色"ACQUISITION"徽章
- 错误信息："文件不存在，链接可能已失效"

**操作步骤：**
1. 新增数据 → 方式 1：下载 URL
2. 文档 URL：`https://example.com/nonexistent_report.pdf`
3. 来源 ID：`测试`
4. 点击"开始下载并处理"

---

### 测试 5：批量上传 📦
**预期结果：**
- 显示进度条
- 实时日志输出
- 最终显示成功/失败统计

**操作步骤：**
1. 新增数据 → 方式 2：批量上传文件
2. 文件路径（每行一个）：
   ```
   F:\hydro_platform_v1\tests\fixtures\test_valid_report.html
   F:\hydro_platform_v1\tests\fixtures\corrupt.pdf
   F:\hydro_platform_v1\tests\fixtures\no_data.html
   ```
3. 来源 ID：`批量测试`
4. 点击"批量处理"
5. 观察进度条和日志

---

## 验证清单

- [ ] 正常文档能成功抽取发电量
- [ ] 损坏文件显示"PARSE"阶段错误
- [ ] 无数据文档显示"EXTRACTION"阶段错误
- [ ] 404 URL 显示"ACQUISITION"阶段错误
- [ ] 错误提示都是中文大白话（不是英文技术错误）
- [ ] 批量上传能显示进度和统计
- [ ] 复核中心能看到成功的记录
- [ ] 数据缺口页面正常加载
- [ ] Top 100 页面正常加载
- [ ] 统计分析页面正常加载

---

## 注意事项

1. **HTML 文件作为测试：** 由于真实 PDF 文件太大，测试使用 HTML 文件。应用会将 HTML 当作文本文档处理。

2. **数据库位置：** `F:\hydro_platform_v1\data\hydropower.sqlite`

3. **清理测试数据：**
   ```sql
   DELETE FROM generation_records WHERE source_id IN ('三峡集团', '测试', '批量测试');
   DELETE FROM documents WHERE source_id IN ('三峡集团', '测试', '批量测试');
   ```

4. **查看调试日志：** 打开浏览器控制台（F12）查看 `[Dashboard]` `[waitForApi]` 等日志

---

## 已知问题

- ✅ JavaScript 语法错误 - 已修复
- ✅ API 等待超时 - 已修复
- ✅ Favicon 404 - 已修复
- ✅ 新架构接入 - 已完成

---

## 下一步开发

根据测试结果，可能需要：
1. 优化 HTML 文档的解析（目前主要针对 PDF）
2. 增加更多错误码的中文映射
3. 改进批量上传的错误恢复机制
4. 添加测试数据的快速清理功能
