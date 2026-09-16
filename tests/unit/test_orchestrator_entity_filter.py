from types import SimpleNamespace

from hydro_platform.pipeline.orchestrator import _prefer_target_entity_candidates


def test_entity_filter_discards_other_station_rows_when_target_is_present():
    candidates = [
        SimpleNamespace(snippet="三峡电站完成发电量 787.90 亿千瓦时"),
        SimpleNamespace(snippet="溪洛渡电站完成发电量 578.04 亿千瓦时"),
        SimpleNamespace(snippet="年度总发电量 1855.81 亿千瓦时"),
    ]
    selected = _prefer_target_entity_candidates(candidates, ("Xiluodu Dam", "溪洛渡电站"))
    assert selected == [candidates[1]]


def test_entity_filter_keeps_generic_candidates_for_single_station_documents():
    candidates = [SimpleNamespace(snippet="A geração de energia foi de 83.879 GWh em 2023")]
    assert _prefer_target_entity_candidates(candidates, ("Itaipu Dam", "ITAIPU")) == candidates
