"""CLI 模块初始化。

使用惰性导出，避免 ``python -m hydro_platform.app.cli.commands`` 时包初始化
先导入 commands，触发 runpy 的重复模块警告。
"""

__all__ = ["cli", "main"]


def __getattr__(name):
    if name in __all__:
        from .commands import cli, main
        return {"cli": cli, "main": main}[name]
    raise AttributeError(name)
