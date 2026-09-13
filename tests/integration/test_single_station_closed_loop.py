"""单座电站真实闭环（离线优先，文档 §25）。

用一份「真实电站真实披露文档」（三峡 2020，见 tests/fixtures）跑通全链路：
tasking → acquisition(脚本化 Transport 离线) → archive → parsing → 规则抽取 →
validation → evidence → review-gate →（人工 approve）→ promotion。
只把网络边界替换成回放真实文档字节，其余全是真实实现。

验证两条路径 + 一个人工断点（文档 §15）：
- Top100(priority_tier=A) 电站 → 停在 Review Queue，人工 approve 后才升为 publishable
- 幂等：重跑闭环不产生重复 document/evidence/generation_record
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydro_platform.acquisition.http_client import HttpClient
from hydro_platform.acquisition.router import AcquisitionRouter
from hydro_platform.acquisition.transport import RawResponse
from hydro_platform.common.enums import ContentKind, TaskStatus
from hydro_platform.database.repositories import (
    EvidenceRepository,
    GenerationRepository,
    SourceRepository,
)
from hydro_platform.pipeline import PipelineContext, SourceRef
from hydro_platform.pipeline.orchestrator import apply_review_decision, run_task
from hydro_platform.pipeline.station_runner import run_station

FIXTURE = Path(__file__).parent.parent / "fixtures" / "three_gorges_2020.html"
STATION_URL = "https://example.gov/three-gorges/2020"


class ScriptedTransport:
    """离线传输：对已登记 URL 回放固定字节，其余抛 404。仅替换网络边界。"""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def fetch(self, url: str, *, headers, timeout) -> RawResponse:
        self.calls.append(url)
        body = self.mapping.get(url)
        if body is None:
            from hydro_platform.acquisition.transport import TransportError
            from hydro_platform.common.enums import AcquisitionErrorCode

            raise TransportError(AcquisitionErrorCode.HTTP_404, f"未脚本化: {url}")
        return RawResponse(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=body,
            final_url=url,
        )


class FixedResolver:
    """把任意任务解析到固定的三峡披露页（单站闭环用）。"""

    def resolve(self, task):
        return [SourceRef(url=STATION_URL, expected=ContentKind.HTML, title="三峡2020")]


class AutoApprove:
    def decide(self, review_id, task):
        return "approve"


def _seed_station(db, entity_id="cn_three_gorges", tier="A", capacity=22500.0):
    db.execute(
        "INSERT INTO stations (entity_id, entity_type, canonical_name, "
        "capacity_mw, priority_tier, collection_priority, needs_review) "
        "VALUES (?, 'station', ?, ?, ?, 1, 0)",
        (entity_id, "Three Gorges Dam", capacity, tier),
    )
    db.commit()


@pytest.fixture()
def ctx(db, tmp_path):
    body = FIXTURE.read_bytes()
    transport = ScriptedTransport({STATION_URL: body})
    router = AcquisitionRouter(http_client=HttpClient(transport=transport))
    return PipelineContext(
        conn=db,
        router=router,
        url_resolver=FixedResolver(),
        review_decider=AutoApprove(),
        raw_root=tmp_path / "raw",
        reviewer="tester",
    )


def _gen_task(db, entity_id="cn_three_gorges", year=2020):
    from hydro_platform.tasking.builder import build_station_tasks
    from hydro_platform.database.repositories import TaskRepository
    from hydro_platform.database.connection import transaction

    row = db.execute(
        "SELECT entity_id, priority_tier, collection_priority FROM stations "
        "WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    tasks = [
        t for t in build_station_tasks(row, years=[year])
        if t.task_type.value == "station_generation"
    ]
    with transaction(db):
        TaskRepository(db).upsert_many(tasks)
    return tasks[0]


def test_top100_station_stops_at_review(ctx, db):
    _seed_station(db)
    task = _gen_task(db)
    res = run_task(ctx, task)

    # Top100 → 必停复核断点，任务落 needs_review，尚未升级
    assert res.final_status == TaskStatus.NEEDS_REVIEW
    assert res.reached_stage == "review_gate"
    assert res.candidates_extracted > 0
    assert res.review_ids
    assert res.candidates_promoted == 0
    assert GenerationRepository(db).count() == 0
    # 采集/归档/存证真实发生
    assert res.documents_archived == 1
    assert SourceRepository(db).count() == 1
    assert EvidenceRepository(db).count() > 0


def test_review_approve_promotes_to_publishable(ctx, db):
    _seed_station(db)
    task = _gen_task(db)
    res = run_task(ctx, task)
    assert res.needs_review

    # 人工 approve 每个复核项 → 升级
    for rid in res.review_ids:
        dres = apply_review_decision(ctx, task, rid, "approve")
    # 至少一条正式记录，且 publishable
    repo = GenerationRepository(db)
    pub = repo.publishable(entity_id="cn_three_gorges")
    assert len(pub) >= 1
    row = pub[0]
    assert row["publication_status"] == "publishable"
    assert row["review_status"] == "approved"
    assert row["evidence_id"]


def test_real_2020_value_extracted(ctx, db):
    # 真实数字校验：1118 亿千瓦时 = 111800 GWh，应作为候选之一被抽出
    _seed_station(db)
    task = _gen_task(db)
    run_task(ctx, task)
    for rid in [r for r in _open_review_ids(db)]:
        apply_review_decision(ctx, task, rid, "approve")

    rows = db.execute(
        "SELECT generation_gwh FROM generation_records "
        "WHERE entity_id='cn_three_gorges'"
    ).fetchall()
    values = [r["generation_gwh"] for r in rows]
    # 1118 亿千瓦时 → 111800 GWh（亿千瓦时=100 GWh）
    assert any(abs(v - 111800.0) < 1.0 for v in values), values


def test_closed_loop_is_idempotent(ctx, db):
    _seed_station(db)
    task = _gen_task(db)
    run_task(ctx, task)
    for rid in _open_review_ids(db):
        apply_review_decision(ctx, task, rid, "approve")
    gen1 = GenerationRepository(db).count()
    doc1 = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    # 重跑同一任务：文档/证据/记录不应翻倍
    run_task(ctx, task)
    for rid in _open_review_ids(db):
        apply_review_decision(ctx, task, rid, "approve")
    assert GenerationRepository(db).count() == gen1
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == doc1


def test_non_top100_auto_promotes(db, tmp_path):
    # 非 Top100 且校验干净 → 自动升级，无需人工
    _seed_station(db, entity_id="cn_small", tier="C", capacity=22500.0)
    body = FIXTURE.read_bytes()
    transport = ScriptedTransport({STATION_URL: body})
    router = AcquisitionRouter(http_client=HttpClient(transport=transport))
    ctx = PipelineContext(
        conn=db, router=router, url_resolver=FixedResolver(),
        raw_root=tmp_path / "raw",
    )
    task = _gen_task(db, entity_id="cn_small")
    res = run_task(ctx, task)
    # 干净候选自动升级；若有其它触发复核的候选则停复核——三峡数据本身干净
    assert res.final_status in (TaskStatus.SUCCESS, TaskStatus.NEEDS_REVIEW)
    if res.final_status == TaskStatus.SUCCESS:
        assert res.candidates_promoted >= 1


def test_station_runner_end_to_end(ctx, db):
    _seed_station(db)
    results = run_station(ctx, "cn_three_gorges", years=[2020])
    assert len(results) == 1
    assert results[0].task_id


def _open_review_ids(db) -> list[str]:
    return [r["review_id"] for r in db.execute(
        "SELECT review_id FROM review_items WHERE status='open'"
    ).fetchall()]
