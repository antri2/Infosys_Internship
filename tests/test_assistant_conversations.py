"""Career Assistant conversations must persist in MySQL and stay user-scoped.

Conversation history is shown in a sidebar, so it has to survive a reload, be
separable per conversation, support rename/delete, and never leak another
user's chat.
"""
import json

import pytest

from database.db import get_db
from services import career_assistant_agent as agent


@pytest.fixture
def session(app, candidate):
    with app.app_context():
        db = get_db()
        yield db


def _ask(app, client, message, session_id=None):
    """Post one assistant turn with the model stubbed out."""
    import routes.assistant as assistant_route
    from services import agent_orchestrator as orch

    calls = []

    def fake_answer(question, context):
        calls.append(question)
        return {
            "answer": f"Grounded reply to: {question}",
            "intent": "general",
            "used_fallback": False,
        }

    original = orch.career_assistant_agent.answer_question
    orch.career_assistant_agent.answer_question = fake_answer
    try:
        payload = {"message": message}
        if session_id is not None:
            payload["session_id"] = session_id
        return client.post("/assistant/message", json=payload), calls
    finally:
        orch.career_assistant_agent.answer_question = original


# ------------------------------------------------------------ persistence ---

def test_conversation_survives_a_page_reload(app, client, candidate):
    response, _ = _ask(app, client, "How do I improve my SQL skills?")
    assert response.status_code == 200, response.get_data(as_text=True)
    session_id = response.get_json()["session_id"]

    # Reopening the page must show the stored messages, not an empty chat.
    html = client.get(f"/assistant/?session_id={session_id}").get_data(as_text=True)
    assert "How do I improve my SQL skills?" in html
    assert "Grounded reply to" in html


def test_messages_are_written_to_mysql(app, session, candidate):
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = candidate["user_id"]
    response, _ = _ask(app, client, "Which skills should I learn next?")
    session_id = response.get_json()["session_id"]

    with session.cursor() as cursor:
        cursor.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY id",
            (session_id,),
        )
        rows = cursor.fetchall()
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "Which skills should I learn next?"


def test_new_chat_creates_a_separate_conversation(app, client, candidate):
    first, _ = _ask(app, client, "First conversation question here.")
    second = client.post("/assistant/reset", json={})
    assert second.status_code == 200
    second_id = second.get_json()["session_id"]
    assert second_id != first.get_json()["session_id"]

    # The chat area starts empty. The first conversation is still listed in the
    # sidebar, which is the point of a history list, so only the messages
    # container is checked here.
    html = client.get(f"/assistant/?session_id={second_id}").get_data(as_text=True)
    messages_html = html.split('id="assistant-messages"', 1)[1].split("</section>", 1)[0]
    assert "First conversation question here." not in messages_html


def test_continuing_a_conversation_keeps_its_context(app, client, candidate):
    first, _ = _ask(app, client, "I want to become an AI Engineer.")
    session_id = first.get_json()["session_id"]
    second, _ = _ask(app, client, "What should I practise?", session_id=session_id)
    assert second.get_json()["session_id"] == session_id

    history = client.get(f"/assistant/history/{session_id}").get_json()
    contents = [m["content"] for m in history["messages"]]
    assert contents == [
        "I want to become an AI Engineer.",
        "Grounded reply to: I want to become an AI Engineer.",
        "What should I practise?",
        "Grounded reply to: What should I practise?",
    ]


# ----------------------------------------------------------------- sidebar ---

def test_sidebar_lists_conversations_with_titles(app, client, candidate):
    _ask(app, client, "How do I prepare for a data analyst interview?")
    html = client.get("/assistant/").get_data(as_text=True)
    assert 'class="assistant-sidebar"' in html
    assert "How do I prepare for a data analyst interview?" in html
    assert "assistant-conversation-open" in html


def test_untitled_conversation_is_derived_from_the_first_question(session, candidate):
    """Conversations saved before the title column existed still read sensibly."""
    session_id = agent.create_session(session, candidate["user_id"])
    agent.append_message(session, candidate["user_id"], session_id, "user",
                         "What should I improve in my resume?", "")
    agent.ensure_session_title(session, candidate["user_id"], session_id,
                               "What should I improve in my resume?")

    items = agent.list_conversations(session, candidate["user_id"])
    assert items[0]["title"] == "What should I improve in my resume?"
    assert items[0]["message_count"] == 1


def test_conversation_list_endpoint(app, client, candidate):
    _ask(app, client, "Give me a learning roadmap for data science.")
    payload = client.get("/assistant/conversations").get_json()
    assert payload["success"] is True
    assert payload["conversations"]
    assert payload["conversations"][0]["title"]


def test_rename_conversation(app, client, candidate):
    response, _ = _ask(app, client, "Some question about SQL.")
    session_id = response.get_json()["session_id"]

    renamed = client.post(f"/assistant/conversations/{session_id}/title",
                          json={"title": "SQL deep dive"})
    assert renamed.status_code == 200
    assert renamed.get_json()["title"] == "SQL deep dive"

    items = client.get("/assistant/conversations").get_json()["conversations"]
    assert items[0]["title"] == "SQL deep dive"


def test_rename_requires_a_title(app, client, candidate):
    response, _ = _ask(app, client, "A question.")
    session_id = response.get_json()["session_id"]
    assert client.post(f"/assistant/conversations/{session_id}/title",
                       json={"title": "   "}).status_code == 400


def test_delete_conversation_removes_its_messages(app, client, candidate, session):
    response, _ = _ask(app, client, "A conversation to delete.")
    session_id = response.get_json()["session_id"]

    deleted = client.delete(f"/assistant/conversations/{session_id}")
    assert deleted.status_code == 200

    with session.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS c FROM chat_sessions WHERE id = %s",
                       (session_id,))
        assert cursor.fetchone()["c"] == 0
        cursor.execute("SELECT COUNT(*) AS c FROM chat_messages WHERE session_id = %s",
                       (session_id,))
        assert cursor.fetchone()["c"] == 0, "messages must cascade with the session"


def test_opening_a_conversation_returns_its_messages(app, client, candidate):
    first, _ = _ask(app, client, "Original question for the history.")
    session_id = first.get_json()["session_id"]
    other = client.post("/assistant/reset", json={}).get_json()["session_id"]

    history = client.get(f"/assistant/history/{session_id}").get_json()
    assert history["session_id"] == session_id
    assert any("Original question" in m["content"] for m in history["messages"])
    assert history["messages"] != []


# -------------------------------------------------------------- isolation ---

def test_another_user_cannot_read_a_conversation(app, candidate, session):
    victim_session = agent.create_session(session, candidate["user_id"])
    agent.append_message(session, candidate["user_id"], victim_session, "user",
                         "Private question from another user.", "")

    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name,email,password_hash,career_status) "
                "VALUES ('Other','other-chat@example.test','x','Fresher')"
            )
            other_id = cursor.lastrowid
        db.commit()

    other = app.test_client()
    with other.session_transaction() as s:
        s["user_id"] = other_id

    assert other.get(f"/assistant/history/{victim_session}").status_code == 404
    assert other.post(f"/assistant/conversations/{victim_session}").status_code == 404
    assert other.post(f"/assistant/conversations/{victim_session}/title",
                      json={"title": "hijacked"}).status_code == 404

    # The other user's sidebar must not contain the victim's conversation.
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM chat_sessions WHERE user_id = %s", (other_id,))
            ids = {row["id"] for row in cursor.fetchall()}
            cursor.execute("DELETE FROM users WHERE id = %s", (other_id,))
        db.commit()
    assert victim_session not in ids

    # And the victim's title was not changed.
    with app.app_context():
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT title FROM chat_sessions WHERE id = %s",
                           (victim_session,))
            assert cursor.fetchone()["title"] is None


def test_conversation_routes_require_login(app):
    anon = app.test_client()
    assert anon.get("/assistant/conversations").status_code == 401
    assert anon.post("/assistant/conversations/1/title",
                     json={"title": "x"}).status_code == 401
    assert anon.delete("/assistant/conversations/1").status_code == 401


# ----------------------------------------------------- no browser-only memory ---

def test_sidebar_is_rendered_from_the_database_not_javascript(app, client, candidate):
    _ask(app, client, "A question that must appear server-side.")
    html = client.get("/assistant/").get_data(as_text=True)
    # The title is inside the server-rendered markup, not built by JS.
    sidebar = html.split('id="assistant-conversations"', 1)[1].split("</aside>", 1)[0]
    assert "A question that must appear server-side." in sidebar


def test_unsafe_question_is_escaped_in_the_sidebar(app, client, candidate):
    _ask(app, client, "<script>alert('xss')</script> how do I prepare?")
    html = client.get("/assistant/").get_data(as_text=True)
    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;" in html