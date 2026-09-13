"""快速测试 LLM 配置 UI。

直接启动桌面应用，导航到设置页面测试：
1. LLM 配置卡片显示
2. 配置表单弹窗
3. 保存功能
4. 连接测试
"""

if __name__ == '__main__':
    from hydro_platform.app.gui.main_window import create_window

    print("正在启动桌面应用...")
    print("启动后：")
    print("1. 点击左侧菜单「设置」")
    print("2. 查看「LLM 配置」卡片")
    print("3. 点击「配置 API Key」按钮")
    print("4. 输入 DeepSeek API Key (sk-...)")
    print("5. 点击保存并测试连接")
    print()

    create_window()
