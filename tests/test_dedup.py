from eaa.db import Database
from eaa.dedup import content_hash, is_new
from eaa.models import Email


def mk(message_id="1", sender="ana@example.test", subject="Reunião de projeto",
       body="Vamos alinhar o escopo na sexta."):
    return Email(message_id, sender, subject, body, "")


def test_identical_content_has_same_hash():
    assert content_hash(mk()) == content_hash(mk())


def test_hash_ignores_message_id():
    assert content_hash(mk(message_id="1")) == content_hash(mk(message_id="2"))


def test_hash_ignores_case_in_sender_and_subject():
    assert content_hash(mk(sender="ANA@Example.test", subject="REUNIÃO DE PROJETO")) == content_hash(mk())


def test_hash_ignores_extra_whitespace_and_newlines():
    spaced = mk(body="Vamos   alinhar\no escopo\n\nna sexta.  ")
    assert content_hash(spaced) == content_hash(mk())


def test_different_body_changes_hash():
    assert content_hash(mk(body="Outro assunto.")) != content_hash(mk())


def test_different_sender_changes_hash():
    assert content_hash(mk(sender="bruno@example.test")) != content_hash(mk())


def test_is_new_detects_forward_with_a_new_message_id(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    first = mk(message_id="1")
    assert is_new(db, first) is True
    db.enqueue("1", 5, "{}", content_hash(first))
    assert is_new(db, mk(message_id="2")) is False


def test_is_new_accepts_distinct_emails(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    first = mk(body="Primeiro e-mail.")
    db.enqueue("1", 5, "{}", content_hash(first))
    assert is_new(db, mk(body="Segundo e-mail.")) is True


def test_is_new_alone_does_not_mark_the_email_as_seen(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    assert is_new(db, mk()) is True
    assert is_new(db, mk()) is True
