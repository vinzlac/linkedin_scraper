"""Direction des messages du thread DOM (issue #13) — fonction pure, sans navigateur."""

from linkedin_scraper.scrapers.messaging import resolve_message_direction

SELF = "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc"
OWN_URL = f"https://www.linkedin.com/in/{SELF}"
OTHER_URL = "https://www.linkedin.com/in/ACoAADWu7CUBftOwi9tV-f5VjTKsEXYShWa2Cek"
EVENT_URN = f"urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-MTc4OTM3ODA2OTg2NWI0NTkyMC0xMDAmOGNlMjA2OWE=)"


def test_css_classes_still_win():
    assert resolve_message_direction("msg-s-event-listitem--other", OWN_URL, EVENT_URN) == "inbound"
    assert resolve_message_direction("msg-s-event-listitem--self", OTHER_URL, EVENT_URN) == "outbound"


def test_falls_back_to_the_sender_profile_id_from_the_event_urn():
    assert resolve_message_direction("msg-s-event-listitem", OWN_URL, EVENT_URN) == "outbound"
    assert resolve_message_direction("msg-s-event-listitem", OTHER_URL, EVENT_URN) == "inbound"


def test_unknown_only_without_any_signal():
    assert resolve_message_direction("msg-s-event-listitem", None, EVENT_URN) == "unknown"
    assert resolve_message_direction("msg-s-event-listitem", OWN_URL, None) == "unknown"
    assert resolve_message_direction("msg-s-event-listitem", OWN_URL, "urn:li:msg_message:garbage") == "unknown"
