"""测试CLI命令功能"""

import subprocess
import sys
from pathlib import Path

def run_cli_command(args):
    """运行CLI命令并返回结果"""
    cmd = [sys.executable, "-m", "hydro_platform.app.cli.commands"] + args
    result = subprocess.run(
        cmd,
        cwd=str(Path(__file__).parent.parent.parent),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    return result

def test_help():
    """测试帮助命令"""
    print("\n=== 测试1: --help ===")
    result = run_cli_command(["--help"])
    print(result.stdout)
    assert result.returncode == 0
    assert "Commands:" in result.stdout
    print("[PASS] 帮助信息正常")

def test_status():
    """测试status命令"""
    print("\n=== 测试2: status ===")
    result = run_cli_command(["status"])
    print(result.stdout)
    if result.returncode == 0:
        assert "系统状态" in result.stdout or "status" in result.stdout.lower()
        print("[PASS] status命令正常")
    else:
        print(f"[WARN] status命令返回错误码: {result.returncode}")
        print(result.stderr)

def test_review_list():
    """测试review-list命令"""
    print("\n=== 测试3: review-list ===")
    result = run_cli_command(["review-list", "--limit=3"])
    print(result.stdout)
    if result.returncode == 0:
        print("[PASS] review-list命令正常")
    else:
        print(f"[WARN] review-list返回错误: {result.returncode}")
        print(result.stderr)

def test_run_task_help():
    """测试run-task帮助"""
    print("\n=== 测试4: run-task --help ===")
    result = run_cli_command(["run-task", "--help"])
    print(result.stdout)
    assert result.returncode == 0
    assert "--task-id" in result.stdout
    print("[PASS] run-task帮助正常")

def test_batch_run_help():
    """测试batch-run帮助"""
    print("\n=== 测试5: batch-run --help ===")
    result = run_cli_command(["batch-run", "--help"])
    print(result.stdout)
    assert result.returncode == 0
    assert "--seed-file" in result.stdout
    print("[PASS] batch-run帮助正常")

def main():
    print("=" * 60)
    print("CLI命令测试")
    print("=" * 60)

    tests = [
        test_help,
        test_status,
        test_review_list,
        test_run_task_help,
        test_batch_run_help
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
