"""快速测试：验证DeepSeek配置和功能"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from hydro_platform.discovery.deepseek_search import DeepSeekSourceFinder

print("=" * 60)
print("DeepSeek Discovery 配置验证")
print("=" * 60)

# 1. 测试配置读取
finder = DeepSeekSourceFinder()

print(f"\n[1] 配置读取")
print(f"  启用状态: {finder.enabled}")

if finder.enabled:
    print(f"  API Key: {finder.api_key[:15]}...")
    print(f"  [OK] 配置成功")
else:
    print(f"  [FAIL] 未找到配置")
    sys.exit(1)

# 2. 测试简单搜索
print(f"\n[2] 功能测试")
print("  测试电站: Three Gorges Dam")

task = {
    "entity_name": "Three Gorges Dam",
    "target_period": "2023",
    "metric": "generation",
    "country": "China"
}

try:
    print("  开始搜索...")
    candidates = finder.find(task, max_candidates=3)

    print(f"  找到候选: {len(candidates)}")

    if candidates:
        print(f"  [OK] DeepSeek搜索正常")
        print(f"\n  前3个候选:")
        for i, c in enumerate(candidates[:3], 1):
            print(f"    {i}. {c['url'][:60]}...")
    else:
        print(f"  [WARN] 未找到候选（可能网络问题）")

except Exception as e:
    print(f"  [FAIL] 搜索失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
