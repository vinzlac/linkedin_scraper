"""Horodatage des messages du thread DOM (issue #13) — fonction pure."""

import pytest

from linkedin_scraper.scrapers.messaging import sent_at_from_event_urn

SELF = "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc"
# base64 de "1789378069865b45920-100&8ce2069a" : epoch ms en tête
URN = f"urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-MTc4OTM3ODA2OTg2NWI0NTkyMC0xMDAmOGNlMjA2OWE=)"


def test_sent_at_is_decoded_from_the_epoch_embedded_in_the_urn():
    assert sent_at_from_event_urn(URN) == "2026-09-14T09:27:49.865000+00:00"


@pytest.mark.parametrize(
    "urn",
    [None, "", "urn:li:msg_message:garbage", "urn:li:msg_message:(urn:li:fsd_profile:x,2-!!!)"],
)
def test_sent_at_is_none_without_a_decodable_timestamp(urn):
    assert sent_at_from_event_urn(urn) is None
