# LLM API Key 管理功能实现总结

## 实现内容

### 1. 后端基础设施

**配置管理 (`hydro_platform/config/`)**
- `llm_config.py`: LLM 配置管理类
  - 存储位置：`~/.hydro_platform/llm_config.json`（用户目录，不随程序移动）
  - 文件权限：chmod 600（Unix）保护敏感信息
  - 方法：`save_deepseek_key()`, `load()`, `get_deepseek_config()`, `is_configured()`

- `providers.json`: DeepSeek 提供商元数据模板
  - 包含模型信息、定价、API 端点等

**LLM 客户端 (`hydro_platform/llm/`)**
- `deepseek_client.py`: DeepSeek API 客户端
  - `test_connection()`: 测试 API Key 有效性
  - `chat()`: 发送对话请求
  - `create_client_from_config()`: 从配置创建客户端的工厂函数

### 2. API 集成

**`hydro_platform/app/api.py`**
- `get_llm_config()`: 获取当前配置状态
- `save_llm_config(provider, api_key, model)`: 保存 API Key
- `test_llm_connection()`: 测试连接

**`hydro_platform/app/gui/main_window.py`**
- 将 3 个 API 方法暴露给前端（通过 pywebview.api）

### 3. 前端 UI

**设置页面 (`hydro_platform/app/web/app.js`)**

添加了 LLM 配置卡片：
- 未配置状态：显示警告提示 + "配置 API Key" 按钮
- 已配置状态：显示提供商/模型信息 + "测试连接" + "重新配置" 按钮
- 显示配置文件路径

配置表单弹窗：
- 提供商选择（当前仅 DeepSeek）
- API Key 输入（password 类型）
- 模型选择（deepseek-chat / deepseek-coder）
- 安全说明（解释存储位置）
- 保存 / 取消按钮

JavaScript 函数：
- `showLLMConfigForm()`: 显示配置弹窗
- `closeLLMConfigModal()`: 关闭弹窗
- `saveLLMConfigFromForm()`: 保存配置
- `testLLMConnection()`: 测试连接（带 loading 状态）

### 4. 测试验证

**单元测试通过**
- `LLMConfig`: 配置保存/加载/查询 ✓
- `DeepSeekClient`: 客户端初始化/工厂函数 ✓
- `Api`: 3 个 LLM API 方法集成 ✓
- `HydroPlatformApp`: GUI 方法暴露 ✓

**测试文件**
- `test_llm_ui.py`: 手动测试启动脚本

## 功能特性

✓ 多用户隔离：每个 Windows 用户独立配置
✓ 程序可移植：配置不随程序移动
✓ 安全保护：文件权限 + 用户目录隔离
✓ 可扩展架构：支持未来添加其他提供商
✓ 用户友好 UI：配置状态可视化 + 连接测试

## 使用方法

1. 启动应用：`python -m hydro_platform.app.main`
2. 点击左侧「设置」菜单
3. 在「LLM 配置」卡片点击「配置 API Key」
4. 输入 DeepSeek API Key（从 https://platform.deepseek.com/api_keys 获取）
5. 选择模型（deepseek-chat 或 deepseek-coder）
6. 保存并测试连接

## 配置文件示例

```json
{
  "deepseek": {
    "api_key": "sk-...",
    "enabled": true,
    "model": "deepseek-chat"
  }
}
```

存储位置：`C:\Users\<用户名>\.hydro_platform\llm_config.json`

## 下一步（可选）

- 添加其他 LLM 提供商（ChatGPT, Claude, Kimi, GLM）
- 实现 API Key 加密存储
- 添加使用量统计
- 集成 LLM 到数据处理流程（智能抽取、报告生成等）
