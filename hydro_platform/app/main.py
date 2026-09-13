"""应用入口点：启动 pywebview 桌面应用。"""

from hydro_platform.app.gui.main_window import create_window


def main():
    """应用主入口。"""
    create_window()


if __name__ == '__main__':
    main()
