"""跨语言来源相关性和规范名称短别名测试。"""

from hydro_platform.discovery.relevance import CandidateRelevanceVerifier


def test_itaipu_portuguese_annual_pdf_is_eligible_from_core_name_and_preview():
    verifier = CandidateRelevanceVerifier()
    candidate = {
        "url": "https://www.itaipu.gov.br/Relatorio_Anual_Itaipu2023_Portugues.pdf",
        "document_type": "pdf",
        "link_text": "ITAIPU BINACIONAL | Relatório Anual 2023",
        "metadata": {
            "content_preview": (
                "Relatório Anual 2023 da Itaipu Binacional. "
                "A produção de energia da usina foi de 83.879 GWh no ano."
            ),
        },
    }
    result = verifier.verify(
        candidate,
        station={
            "canonical_name": "Itaipu Dam (Paraguay side)",
            "local_name": "Usina Hidrelétrica de Itaipu",
            "aliases": ["Itaipu Dam (Paraguay side)", "Usina Hidrelétrica de Itaipu"],
        },
        target_period="2023",
    )

    assert result.eligible is True
    assert result.period_scope == "annual"


def test_portuguese_annual_report_history_date_does_not_trigger_partial_scope():
    verifier = CandidateRelevanceVerifier()
    result = verifier.verify(
        {
            "url": "https://www.itaipu.gov.br/Relatorio_Anual_Itaipu2023_Portugues.pdf",
            "link_text": "Relatório Anual 2023",
            "metadata": {
                "content_preview": (
                    "Em 2023 a produção de energia da Usina Hidrelétrica de ITAIPU "
                    "foi de 83.879 GWh. Em 39 anos de geração, desde 5 de maio de 1984 "
                    "até 31 de dezembro de 2023, a produção acumulada atingiu 2.984.711 GWh."
                ),
            },
        },
        station={
            "canonical_name": "Itaipu Dam (Paraguay side)",
            "local_name": "Usina Hidrelétrica de Itaipu",
            "aliases": ["Itaipu Dam (Paraguay side)", "Usina Hidrelétrica de Itaipu"],
        },
        target_period="2023",
    )

    assert result.eligible is True
    assert result.period_scope == "annual"


def test_json_alias_string_does_not_match_as_literal():
    verifier = CandidateRelevanceVerifier()
    result = verifier.verify(
        {
            "url": "https://example.test/report",
            "link_text": "السد العالي 2022 annual generation report",
        },
        station={
            "canonical_name": "Aswan High Dam",
            "local_name": "السد العالي",
            "aliases": '["Aswan High Dam", "السد العالي"]',
        },
        target_period="2022",
    )

    assert result.reason != "未找到目标电站名称、当地名称或别名"


def test_sse_operator_annual_disclosure_can_defer_station_match_to_pdf_body():
    verifier = CandidateRelevanceVerifier()
    result = verifier.verify(
        {
            "url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-01-08/600900_20250108_8R1Z.pdf",
            "link_text": "长江电力2024年发电量完成情况公告",
            "source_type": "official",
            "document_type": "pdf",
            "discovery_method": "sse_official_disclosure",
            "metadata": {
                "issuer_name": "中国长江电力股份有限公司",
                "security_code": "600900",
            },
        },
        station={
            "canonical_name": "Three Gorges Dam hydroelectric plant",
            "local_name": "长江三峡水电站",
            "operator": "China Yangzi River Three Gorges Group",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is True
    assert result.score == 0.72
    assert "正文中确认" in result.reason
    assert result.period_scope == "annual"


def test_sse_operator_quarterly_disclosure_is_not_promoted_to_annual_lead():
    verifier = CandidateRelevanceVerifier()
    result = verifier.verify(
        {
            "url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-10-12/600900_20241012_MEJE.pdf",
            "link_text": "长江电力2024年三季度发电量完成情况公告",
            "source_type": "official",
            "document_type": "pdf",
            "discovery_method": "sse_official_disclosure",
            "metadata": {
                "issuer_name": "中国长江电力股份有限公司",
                "security_code": "600900",
            },
        },
        station={
            "canonical_name": "Baihetan hydroelectric plant",
            "local_name": "金沙江白鹤滩水电站",
            "operator": "China Yangzi River Three Gorges Group",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "非全年" in result.reason


def test_half_year_disclosure_is_not_promoted_to_annual_generation():
    result = CandidateRelevanceVerifier().verify(
        {
            "url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-07-05/600900_20240705_7XK3.pdf",
            "link_text": "长江电力2024年半年度发电量完成情况公告",
            "source_type": "official",
            "document_type": "pdf",
            "discovery_method": "sse_official_disclosure",
            "metadata": {
                "issuer_name": "中国长江电力股份有限公司",
                "security_code": "600900",
            },
        },
        station={
            "canonical_name": "Xiluodu hydroelectric plant",
            "local_name": "金沙江溪洛渡水电站",
            "operator": "China Yangzi River Three Gorges Group",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "非全年" in result.reason


def test_portuguese_generated_phrase_and_year_scope_are_eligible():
    result = CandidateRelevanceVerifier().verify(
        {
            "url": "https://cenarioenergia.com.br/2025/08/06/norte-energia-belo-monte-2024.html",
            "link_text": "Norte Energia divulga resultados de Belo Monte",
            "metadata": {
                "content_preview": (
                    "Em 2024, Belo Monte gerou 22.690 GWh de energia renovável, "
                    "com desempenho operacional da usina."
                ),
            },
        },
        station={
            "canonical_name": "Belo Monte hydroelectric plant",
            "local_name": "Usina Hidrelétrica Belo Monte",
            "operator": "Norte Energia",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is True
    assert result.period_scope == "annual"
    assert "全年口径已确认" in result.reason


def test_portuguese_partial_month_does_not_become_annual_generation():
    result = CandidateRelevanceVerifier().verify(
        {
            "url": "https://example.test/belo-monte-2024-janeiro.html",
            "link_text": "Belo Monte gera energia em janeiro de 2024",
            "metadata": {
                "content_preview": (
                    "Em janeiro de 2024, Belo Monte gerou 1.200 GWh de energia."
                ),
            },
        },
        station={
            "canonical_name": "Belo Monte hydroelectric plant",
            "local_name": "Usina Hidrelétrica Belo Monte",
            "operator": "Norte Energia",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"


def test_portuguese_beginning_of_year_article_does_not_become_annual_generation():
    result = CandidateRelevanceVerifier().verify(
        {
            "url": "https://flj.com.br/economia/el-nino-deve-reduzir-geracao-de-energia-de-belo-monte-em-2024/",
            "link_text": "El Niño deve reduzir geração de energia de Belo Monte em 2024",
            "metadata": {
                "search_snippet": (
                    "O padrão climático El Niño deve reduzir a geração da usina hidrelétrica "
                    "de Belo Monte no início de 2024."
                ),
            },
        },
        station={
            "canonical_name": "Belo Monte hydroelectric plant",
            "local_name": "Usina Hidrelétrica Belo Monte",
            "operator": "Norte Energia",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "非全年" in result.reason


def test_portuguese_partial_current_year_is_not_rescued_by_prior_year_annual_sentence():
    result = CandidateRelevanceVerifier().verify(
        {
            "url": "https://www.cnnbrasil.com.br/economia/macroeconomia/usina-de-belo-monte-atende-7-da-demanda-energetica-apos-fim-da-seca/",
            "link_text": "Usina de Belo Monte atende 7% da demanda energética após fim da seca",
            "metadata": {
                "content_preview": (
                    "Durante o primeiro semestre de 2024, Belo Monte foi a hidrelétrica "
                    "que mais entregou energia, produzindo 20.414 GWh. "
                    "No ano passado, Belo Monte gerou 31.521 GWh."
                ),
            },
        },
        station={
            "canonical_name": "Belo Monte hydroelectric plant",
            "local_name": "Usina Hidrelétrica Belo Monte",
            "operator": "Norte Energia",
            "aliases": [],
        },
        target_period="2024",
    )

    assert result.eligible is False
    assert result.period_scope == "partial"
    assert "非全年" in result.reason
