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
