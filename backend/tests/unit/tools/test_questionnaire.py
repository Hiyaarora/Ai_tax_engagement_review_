from app.tools.questionnaire import get_questionnaire_answers


def test_all_answers_when_no_section(acme_data):
    r = get_questionnaire_answers(acme_data)
    assert len(r.answers) == 10
    assert r.available_sections == ["General", "Physical presence", "Registrations"]
    assert r.source == "tool:get_questionnaire_answers"


def test_section_filter_is_case_insensitive(acme_data):
    r = get_questionnaire_answers(acme_data, section="physical PRESENCE")
    assert {a.id for a in r.answers} == {
        "inventory_tx",
        "inventory_other",
        "employees_outside_co",
        "contractors",
    }
    assert r.section == "Physical presence"


def test_unknown_section_returns_empty_with_available_sections(acme_data):
    r = get_questionnaire_answers(acme_data, section="Payroll")
    assert r.answers == [] and "Registrations" in r.available_sections
