from hydro_platform.app.api import Api


def test_review_api_does_not_publish_missing_record(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRO_DATA_DIR", str(tmp_path / "data"))
    api = Api("test")
    assert api.approve_record(999)["status"] == "failed"
    assert api.reject_record(999, "test")["status"] == "failed"
