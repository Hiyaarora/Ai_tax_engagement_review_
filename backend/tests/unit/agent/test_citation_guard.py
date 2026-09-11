from app.agent.citation_guard import apply_citation_guard
from app.agent.review_context import ReviewContext
from app.models.evidence import EvidenceHit
from app.models.review import Citation, ReviewDraft, RiskFlag, ToolFinding


def _hit(chunk_id: str, page: int, excerpt: str) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=chunk_id,
        doc_id=chunk_id.split("-")[0],
        doc_type="questionnaire",
        source_name="questionnaire.pdf",
        page=page,
        excerpt=excerpt,
        score=0.03,
    )


def _ctx(acme_data, hits: list[EvidenceHit], tool_calls: list[str]) -> ReviewContext:
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)
    ctx.record_hits(hits)
    ctx.tool_calls = list(tool_calls)
    return ctx


def _flag(citations: list[Citation], findings: list[ToolFinding], flag_id: str = "F1") -> RiskFlag:
    return RiskFlag(
        id=flag_id,
        title="t",
        state="TX",
        category="physical_presence",
        risk_level="high",
        explanation="e",
        retrieved_evidence=citations,
        tool_findings=findings,
        recommended_human_action="a",
    )


def _draft(*flags: RiskFlag) -> ReviewDraft:
    return ReviewDraft(
        overall_summary="s",
        overall_risk_level="high",
        risk_flags=list(flags),
        states_reviewed_without_flags=[],
    )


def test_valid_citation_is_kept_and_normalised_to_the_retrieved_hit(acme_data):
    ctx = _ctx(
        acme_data, [_hit("questionnaire-p1-c1", 1, "inventory in Texas? | Yes | 3PL in Dallas")], []
    )
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="questionnaire-p1-c1",
                    source_name="WRONG.pdf",
                    page=9,
                    quote="3PL in Dallas",
                )
            ],
            [],
        )
    )

    result, report = apply_citation_guard(draft, ctx)

    c = result.risk_flags[0].retrieved_evidence[0]
    assert (c.source_name, c.page, c.quote) == ("questionnaire.pdf", 1, "3PL in Dallas")
    assert report.dropped_citations == [] and report.corrected_citations == ["questionnaire-p1-c1"]


def test_citation_to_chunk_never_retrieved_is_removed(acme_data):
    ctx = _ctx(acme_data, [_hit("questionnaire-p1-c1", 1, "x")], [])
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="questionnaire-p1-c1",
                    source_name="questionnaire.pdf",
                    page=1,
                    quote="x",
                ),
                Citation(
                    chunk_id="made-up-p3-c0", source_name="secret.pdf", page=3, quote="fabricated"
                ),
            ],
            [],
        )
    )

    result, report = apply_citation_guard(draft, ctx)

    assert [c.chunk_id for c in result.risk_flags[0].retrieved_evidence] == ["questionnaire-p1-c1"]
    assert report.dropped_citations == ["made-up-p3-c0"]


def test_quote_not_present_in_retrieved_chunk_is_cleared(acme_data):
    ctx = _ctx(
        acme_data,
        [_hit("questionnaire-p1-c1", 1, "Does the company hold inventory in Texas? | Yes")],
        [],
    )
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="questionnaire-p1-c1",
                    source_name="q.pdf",
                    page=1,
                    quote="Texas warehouse burned down",
                )
            ],
            [],
        )
    )

    result, report = apply_citation_guard(draft, ctx)

    assert result.risk_flags[0].retrieved_evidence[0].quote == ""
    assert [u.chunk_id for u in report.unverified_quotes] == ["questionnaire-p1-c1"]


def test_quote_match_ignores_whitespace_and_case(acme_data):
    ctx = _ctx(
        acme_data, [_hit("q-p1-c0", 1, "Does the company hold\n\ninventory in Texas? | Yes")], []
    )
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="q-p1-c0",
                    source_name="q.pdf",
                    page=1,
                    quote="hold inventory in texas? | yes",
                )
            ],
            [],
        )
    )
    result, report = apply_citation_guard(draft, ctx)
    assert result.risk_flags[0].retrieved_evidence[0].quote == "hold inventory in texas? | yes"
    assert report.unverified_quotes == []


def test_tool_finding_from_a_tool_that_was_not_called_is_removed(acme_data):
    ctx = _ctx(acme_data, [], ["analyze_sales_by_state"])
    draft = _draft(
        _flag(
            [],
            [
                ToolFinding(tool="analyze_sales_by_state", finding="TX revenue 620,000.00"),
                ToolFinding(tool="get_payroll_records", finding="invented"),
            ],
        )
    )

    result, report = apply_citation_guard(draft, ctx)

    assert [f.tool for f in result.risk_flags[0].tool_findings] == ["analyze_sales_by_state"]
    assert report.dropped_tool_findings == ["get_payroll_records"]


def test_flag_left_with_no_evidence_is_reported_but_kept_for_human_review(acme_data):
    ctx = _ctx(acme_data, [], [])
    draft = _draft(
        _flag(
            [Citation(chunk_id="ghost-p1-c0", source_name="g.pdf", page=1, quote="q")],
            [],
            flag_id="GHOST",
        ),
        _flag([], [ToolFinding(tool="x", finding="y")], flag_id="ALSO-GHOST"),
    )

    result, report = apply_citation_guard(draft, ctx)

    assert [f.id for f in result.risk_flags] == ["GHOST", "ALSO-GHOST"]
    assert report.flags_without_evidence == ["GHOST", "ALSO-GHOST"]


def test_guard_does_not_mutate_the_input_draft(acme_data):
    ctx = _ctx(acme_data, [], [])
    draft = _draft(
        _flag([Citation(chunk_id="ghost-p1-c0", source_name="g.pdf", page=1, quote="q")], [])
    )
    apply_citation_guard(draft, ctx)
    assert len(draft.risk_flags[0].retrieved_evidence) == 1


def test_quote_matching_ignores_table_pipes_and_punctuation(acme_data):
    ctx = _ctx(
        acme_data,
        [
            _hit(
                "q-p1-c0",
                1,
                "| inventory_tx | Does the company hold inventory in Texas? | Yes | 3PL. |",
            )
        ],
        [],
    )
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="q-p1-c0",
                    source_name="q.pdf",
                    page=1,
                    quote="Does the company hold inventory in Texas? Yes",
                )
            ],
            [],
        )
    )
    result, report = apply_citation_guard(draft, ctx)
    assert (
        result.risk_flags[0].retrieved_evidence[0].quote
        == "Does the company hold inventory in Texas? Yes"
    )
    assert report.unverified_quotes == []


def test_rejected_quote_text_is_kept_in_the_report_for_debugging(acme_data):
    ctx = _ctx(acme_data, [_hit("q-p1-c0", 1, "Does the company hold inventory in Texas? Yes")], [])
    draft = _draft(
        _flag(
            [
                Citation(
                    chunk_id="q-p1-c0", source_name="q.pdf", page=1, quote="inventory in Nevada"
                )
            ],
            [],
        )
    )
    _, report = apply_citation_guard(draft, ctx)
    assert [u.model_dump() for u in report.unverified_quotes] == [
        {"chunk_id": "q-p1-c0", "quote": "inventory in Nevada"}
    ]
