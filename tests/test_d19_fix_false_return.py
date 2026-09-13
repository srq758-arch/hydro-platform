"""D19修复：将返回False的测试改为正确的断言失败。

问题：32个测试函数通过返回False表示失败，但pytest将其视为通过。
解决：修改这些测试函数，使其在失败时抛出AssertionError而不是返回False。

受影响的测试文件：
- tests/test_generation_ranking.py (7个测试)
- tests/test_integration.py (7个测试)
- tests/test_master_registry.py (5个测试)
- tests/test_project_registry.py (6个测试)
- tests/test_project_station_linking.py (7个测试)
"""

import ast
import sys
from pathlib import Path


def fix_test_file(file_path: Path) -> tuple[bool, str]:
    """修复单个测试文件中的返回False问题。

    将形如：
        def test_xxx():
            try:
                ...
                return True
            except Exception as e:
                print(...)
                return False

    改为：
        def test_xxx():
            try:
                ...
                # 测试通过
            except Exception as e:
                pytest.fail(f"测试失败: {e}")

    Returns:
        (是否修改, 修改说明)
    """
    if not file_path.exists():
        return False, f"文件不存在: {file_path}"

    content = file_path.read_text(encoding='utf-8')
    original_content = content

    # 策略1: 替换 "return True" 为空（测试通过不需要返回值）
    content = content.replace('\n        return True\n', '\n        # 测试通过\n')
    content = content.replace('\n            return True\n', '\n            # 测试通过\n')

    # 策略2: 替换 "return False" 为 "pytest.fail(...)"
    # 需要保留上下文中的错误信息
    lines = content.split('\n')
    modified_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # 检测 "return False" 模式
        if 'return False' in line and not line.strip().startswith('#'):
            indent = len(line) - len(line.lstrip())

            # 查找前面的错误消息
            error_msg = "测试失败"
            for j in range(i-1, max(0, i-5), -1):
                prev_line = lines[j]
                if 'print(' in prev_line and ('FAIL' in prev_line or 'Error' in prev_line or '失败' in prev_line):
                    # 提取print中的消息
                    try:
                        if 'f"' in prev_line or "f'" in prev_line:
                            # f-string
                            start = prev_line.find('f"') if 'f"' in prev_line else prev_line.find("f'")
                            if start >= 0:
                                quote = prev_line[start+1]
                                end = prev_line.find(quote, start+2)
                                if end > 0:
                                    error_msg = prev_line[start+2:end]
                        elif '"' in prev_line or "'" in prev_line:
                            # 普通字符串
                            for quote in ['"', "'"]:
                                if quote in prev_line:
                                    parts = prev_line.split(quote)
                                    if len(parts) >= 3:
                                        error_msg = parts[1]
                                    break
                    except:
                        pass
                    break

            # 替换为 pytest.fail()
            modified_lines.append(' ' * indent + f'pytest.fail("{error_msg}")')
        else:
            modified_lines.append(line)

        i += 1

    content = '\n'.join(modified_lines)

    # 确保导入pytest
    if 'import pytest' not in content and 'pytest.fail' in content:
        # 在文件开头的import区域添加
        lines = content.split('\n')
        import_index = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                import_index = i + 1
        lines.insert(import_index, 'import pytest')
        content = '\n'.join(lines)

    if content != original_content:
        file_path.write_text(content, encoding='utf-8')
        return True, f"已修复: 移除return True/False，改用pytest.fail()"

    return False, "无需修改"


def main():
    """修复所有受影响的测试文件。"""
    test_dir = Path(__file__).parent

    affected_files = [
        test_dir / "test_generation_ranking.py",
        test_dir / "test_integration.py",
        test_dir / "test_master_registry.py",
        test_dir / "test_project_registry.py",
        test_dir / "test_project_station_linking.py",
    ]

    print("D19修复：将返回False的测试改为正确的pytest断言")
    print("=" * 60)

    for file_path in affected_files:
        print(f"\n处理: {file_path.name}")
        modified, message = fix_test_file(file_path)
        if modified:
            print(f"  [OK] {message}")
        else:
            print(f"  [-] {message}")

    print("\n" + "=" * 60)
    print("修复完成。请运行 pytest 验证测试。")
    print("\n注意：修复后的测试可能会失败，这是正常的。")
    print("之前这些测试返回False但被算作通过，现在会正确报告失败。")


if __name__ == "__main__":
    main()
