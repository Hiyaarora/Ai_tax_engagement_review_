from app.tools.employee_locations import get_employee_locations


def test_acme_locations_split_employees_from_other_presence(acme_data):
    r = get_employee_locations(acme_data)
    assert r.home_state == "CO"
    assert r.states_with_employees == ["CO", "WA"]
    assert r.states_with_other_presence == ["TX"]
    assert r.total_headcount == 40
    assert any(loc.state == "WA" and loc.headcount == 2 for loc in r.locations)
    assert r.source == "tool:get_employee_locations"
