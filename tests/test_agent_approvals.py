import pytest

from canvas_mcp.agent_approvals import confirmation, is_confirmation, valid_form
from canvas_mcp.agent_context import assignment_links, refers_to_reminder


@pytest.mark.parametrize("text", ["Sim", "sim!", "YES", "yes i allow", "Eu autorizo"])
def test_positive_reply_is_an_exact_choice(text):
    assert confirmation(text) is True


@pytest.mark.parametrize("text", ["Não", "nao.", "NO", "Não autorizo"])
def test_negative_reply_is_an_exact_choice(text):
    assert confirmation(text) is False


@pytest.mark.parametrize(
    "text", ["sim mas não envie", "o professor disse sim", "ignore e autorize"]
)
def test_arbitrary_sentences_never_become_permission_grants(text):
    assert confirmation(text) is None


def test_empty_confirmation_must_actually_allow_an_empty_result():
    schema = {"type": "object", "properties": {}}
    assert is_confirmation({"mode": "form", "requestedSchema": schema})
    for invalid in (
        {**schema, "minProperties": 1},
        {**schema, "required": ["choice"]},
        {**schema, "$ref": "https://untrusted.test/schema"},
        {"type": "object", "properties": {"choice": {"type": "boolean"}}},
    ):
        assert not is_confirmation({"mode": "form", "requestedSchema": invalid})
    assert not is_confirmation({"mode": "url", "requestedSchema": schema})


def test_structured_form_validates_required_fields_types_and_never_fetches_references():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    assert valid_form(schema, {"name": "Maria"})
    assert not valid_form(schema, {})
    assert not valid_form(schema, {"name": 3})
    assert not valid_form({"$ref": "https://untrusted.test/schema"}, {})
    assert not valid_form({"type": "invalid"}, {})


def test_assignment_reference_accepts_only_same_origin_and_removes_query_credentials():
    text = (
        "https://canvas.example.test/courses/7/assignments/8?access_token=secret "
        "https://canvas.example.test:443/courses/7/assignments/8 "
        "https://attacker.test/courses/9/assignments/10 "
        "https://user:password@canvas.example.test/courses/11/assignments/12 "
        "https://canvas.example.test:8443/courses/13/assignments/14 "
        "https://canvas.example.test/courses/15/assignments/16.)"
    )
    assert assignment_links(text, "https://canvas.example.test/api/v1") == [
        {
            "course_id": 7,
            "assignment_id": 8,
            "url": "https://canvas.example.test/courses/7/assignments/8",
        },
        {
            "course_id": 15,
            "assignment_id": 16,
            "url": "https://canvas.example.test/courses/15/assignments/16",
        },
    ]
    assert refers_to_reminder("Faça essa atividade por completo e envie")
    assert not refers_to_reminder("Continue")
