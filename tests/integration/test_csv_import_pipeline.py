"""CSV 导入必须走 Candidate→Evidence→Document→Review 闭环。"""

from hydro_platform.app.api import Api


def test_csv_import_queues_candidates_without_publishing(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        "INSERT INTO stations(entity_id, canonical_name, country, capacity_mw) VALUES (?, ?, ?, ?)",
        ("csv-station", "CSV Station", "CN", 1000),
    )
    conn.commit()
    conn.close()

    csv_content = (
        "entity_id,period_label,generation_gwh,canonical_name,unit_raw,period_type,value_type,measurement_scope\n"
        "csv-station,2024,123.4,CSV Station,GWh,calendar_year,actual,plant\n"
        "unknown-station,2024,nope,Unknown,GWh,calendar_year,actual,plant\n"
        "csv-station,2023,10,CSV Station,MW,calendar_year,actual,plant\n"
        "csv-station,2022,5,CSV Station,GWh,calendar_year,forecast,plant\n"
    )
    result = api.import_csv_batch(csv_content)

    assert result["success"] is True
    assert result["imported_count"] == 1
    assert result["skipped_count"] == 3
    assert result["details"][0]["status"] == "queued_for_review"
    assert result["details"][0]["review_id"]

    conn = api.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM generation_records").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM extraction_candidates").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM candidate_evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM review_items WHERE status = 'open'").fetchone()[0] == 1
    task = conn.execute("SELECT * FROM tasks").fetchone()
    assert task is not None
    assert task["status"] == "needs_review"
    assert conn.execute("SELECT task_id FROM extraction_candidates").fetchone()[0] == task["task_id"]
    assert conn.execute("SELECT task_id FROM evidence").fetchone()[0] == task["task_id"]
    assert conn.execute("SELECT task_id FROM review_items").fetchone()[0] == task["task_id"]
    assert conn.execute("SELECT COUNT(*) FROM documents WHERE content_kind = 'csv'").fetchone()[0] == 1
    conn.close()


def test_csv_import_is_idempotent_for_same_content(monkeypatch, tmp_path):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        "INSERT INTO stations(entity_id, canonical_name, country) VALUES (?, ?, ?)",
        ("csv-station", "CSV Station", "CN"),
    )
    conn.commit()
    conn.close()

    csv_content = "entity_id,period_label,generation_gwh\ncsv-station,2024,123.4\n"
    first = api.import_csv_batch(csv_content)
    second = api.import_csv_batch(csv_content)
    assert first["details"][0]["candidate_id"] == second["details"][0]["candidate_id"]
    assert second["imported_count"] == 0
    assert second["existing_count"] == 1
    assert second["details"][0]["status"] == "already_queued"

    conn = api.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM extraction_candidates").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    conn.close()


def test_csv_review_approve_and_reject_complete_auditable_task_runs(monkeypatch, tmp_path):
    """CSV 候选可真实完成通过/驳回闭环，不触发 task_runs 外键错误。"""
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    conn = api.get_db_connection()
    conn.executemany(
        "INSERT INTO stations(entity_id, canonical_name, country, capacity_mw) VALUES (?, ?, ?, ?)",
        [("csv-approve", "CSV Approve", "CN", 1000), ("csv-reject", "CSV Reject", "CN", 1000)],
    )
    conn.commit()
    conn.close()

    result = api.import_csv_batch(
        "entity_id,period_label,generation_gwh\n"
        "csv-approve,2024,123.4\n"
        "csv-reject,2024,88.8\n"
    )
    assert result["success"] is True
    approve_review = result["details"][0]["review_id"]
    reject_review = result["details"][1]["review_id"]

    assert api.approve_record(approve_review)["status"] == "success"
    assert api.reject_record(reject_review, "现场核验不通过")["status"] == "success"

    conn = api.get_db_connection()
    assert conn.execute("SELECT status FROM review_items WHERE review_id = ?", (approve_review,)).fetchone()[0] == "approve"
    assert conn.execute("SELECT status FROM review_items WHERE review_id = ?", (reject_review,)).fetchone()[0] == "reject"
    assert conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM task_runs WHERE status = 'success'").fetchone()[0] == 2
    assert conn.execute(
        "SELECT publication_status, review_status FROM generation_records WHERE entity_id = 'csv-approve'"
    ).fetchone()[0] == "publishable"
    assert conn.execute(
        "SELECT COUNT(*) FROM generation_records WHERE entity_id = 'csv-reject'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0] == 0
    conn.close()


def test_legacy_csv_review_without_task_is_adopted_on_approval(monkeypatch, tmp_path):
    """旧 CSV 复核项 task_id 为 NULL 时，审核动作按需补齐其父任务。"""
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path))
    api = Api(data_mode="test")
    api.initialize()
    conn = api.get_db_connection()
    conn.execute(
        "INSERT INTO stations(entity_id, canonical_name, country, capacity_mw) VALUES (?, ?, ?, ?)",
        ("csv-legacy", "CSV Legacy", "CN", 1000),
    )
    conn.commit()
    conn.close()

    imported = api.import_csv_batch("entity_id,period_label,generation_gwh\ncsv-legacy,2024,42\n")
    review_id = imported["details"][0]["review_id"]
    conn = api.get_db_connection()
    candidate_id = conn.execute(
        "SELECT candidate_id FROM review_items WHERE review_id = ?", (review_id,)
    ).fetchone()[0]
    conn.execute("UPDATE review_items SET task_id = NULL WHERE review_id = ?", (review_id,))
    conn.execute("UPDATE extraction_candidates SET task_id = NULL WHERE candidate_id = ?", (candidate_id,))
    conn.execute(
        "UPDATE evidence SET task_id = NULL WHERE evidence_id IN "
        "(SELECT evidence_id FROM candidate_evidence WHERE candidate_id = ?)",
        (candidate_id,),
    )
    conn.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()

    assert api.approve_record(review_id)["status"] == "success"

    conn = api.get_db_connection()
    task_id = conn.execute("SELECT task_id FROM review_items WHERE review_id = ?", (review_id,)).fetchone()[0]
    assert task_id
    assert conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()[0] == "success"
    assert conn.execute("SELECT COUNT(*) FROM task_runs WHERE task_id = ? AND status = 'success'", (task_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0] == 0
    conn.close()
