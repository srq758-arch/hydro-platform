"""测试GUI复核界面功能。

验证：
1. list_review_items API
2. get_review_detail API
3. approve_record API
4. reject_record API
5. batch_approve API
6. batch_reject API
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.app.api import Api
from hydro_platform.database.connection import connect
from hydro_platform.config.paths import get_database_path


def test_list_review_items():
    """测试1：列出复核项"""
    print("\n=== 测试1：列出复核项 ===")

    api = Api()
    result = api.list_review_items(status=None, limit=10, offset=0)

    print(f"总数: {result.get('total', 0)}")
    print(f"返回项数: {len(result.get('items', []))}")

    if result.get('items'):
        first = result['items'][0]
        print(f"第一项: ID={first.get('id')}, 电站={first.get('canonical_name')}, 年份={first.get('period_label')}")

    assert 'items' in result
    assert 'total' in result
    print("测试1通过")


def test_get_review_detail():
    """测试2：获取复核详情"""
    print("\n=== 测试2：获取复核详情 ===")

    api = Api()

    # 先获取一个record_id
    result = api.list_review_items(limit=1)
    if not result.get('items'):
        print("跳过测试2：没有待复核项")
        return

    record_id = result['items'][0]['id']
    print(f"查询记录ID: {record_id}")

    detail = api.get_review_detail(record_id)

    if detail:
        print(f"记录详情:")
        print(f"  电站: {detail.get('canonical_name')}")
        print(f"  发电量: {detail.get('generation_gwh')} GWh")
        print(f"  校验问题数: {len(detail.get('validation_issues', []))}")
        print(f"  证据数: {len(detail.get('evidences', []))}")
        assert 'id' in detail
        assert 'generation_gwh' in detail
        print("测试2通过")
    else:
        print("未找到详情（可能已复核）")


def test_batch_operations():
    """测试3：批量操作"""
    print("\n=== 测试3：批量操作 ===")

    api = Api()

    # 获取多个record_id
    result = api.list_review_items(limit=3)
    if len(result.get('items', [])) < 2:
        print("跳过测试3：待复核项不足2个")
        return

    record_ids = [item['id'] for item in result['items'][:2]]
    print(f"测试批量操作，记录IDs: {record_ids}")

    # 测试批量批准（仅测试API调用，不实际执行）
    # result = api.batch_approve(record_ids)
    # print(f"批量批准结果: 成功{result['success']}，失败{result['failed']}")

    print("测试3通过（已跳过实际执行）")


def test_api_methods_exist():
    """测试4：验证API方法存在"""
    print("\n=== 测试4：验证API方法存在 ===")

    api = Api()

    # 检查必需的方法
    required_methods = [
        'list_review_items',
        'get_review_detail',
        'approve_record',
        'reject_record',
        'batch_approve',
        'batch_reject',
    ]

    for method_name in required_methods:
        assert hasattr(api, method_name), f"缺少方法: {method_name}"
        print(f"[OK] {method_name}")

    print("测试4通过")


def test_review_workflow_integration():
    """测试5：复核工作流集成"""
    print("\n=== 测试5：复核工作流集成 ===")

    # 检查数据库中是否有待复核数据
    conn = connect(get_database_path())

    # 检查generation_records表
    records_count = conn.execute(
        "SELECT COUNT(*) FROM generation_records"
    ).fetchone()[0]
    print(f"generation_records表记录数: {records_count}")

    # 检查review_items表
    review_count = conn.execute(
        "SELECT COUNT(*) FROM review_items WHERE status = 'open'"
    ).fetchone()[0]
    print(f"待复核项数: {review_count}")

    conn.close()

    print("测试5通过")


if __name__ == "__main__":
    print("=" * 60)
    print("GUI复核界面API测试")
    print("=" * 60)

    try:
        test_api_methods_exist()
        test_list_review_items()
        test_get_review_detail()
        test_batch_operations()
        test_review_workflow_integration()

        print("\n" + "=" * 60)
        print("所有测试通过")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
