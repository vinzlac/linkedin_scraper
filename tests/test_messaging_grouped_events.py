"""Messages consécutifs d'un même expéditeur dans le thread DOM (issue #13).

LinkedIn n'affiche nom et lien profil qu'une fois par groupe : les messages
suivants du groupe n'ont ni `sender_url` ni classe `--self`/`--other`.
"""

import pytest

SELF = "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc"
OTHER = "ACoAADWu7CUBftOwi9tV-f5VjTKsEXYShWa2Cek"


def _event(sender_id, text, link=None):
    urn = f"urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-{text[:3]})"
    header = (
        f'<a class="msg-s-message-group__profile-link" href="/in/{sender_id}">'
        f'<span class="msg-s-message-group__name">{link}</span></a>'
        if link
        else ""
    )
    return (
        f'<li class="msg-s-event-listitem" data-event-urn="{urn}">{header}'
        f'<div class="msg-s-event-listitem__body">{text}</div></li>'
    )


HTML = "<ul>" + "".join(
    [
        _event(OTHER, "bonjour", link="Fabien"),
        _event(OTHER, "deuxieme du meme groupe"),
        _event(SELF, "ma reponse", link="Vincent"),
        _event(SELF, "ma reponse suite"),
    ]
) + "</ul>"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grouped_events_inherit_the_group_sender():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(HTML)
        messages = await MessagingScraper(page)._extract_messages("conv", limit=10)
        await browser.close()

    assert [m.direction for m in messages] == [
        "inbound", "inbound", "outbound", "outbound",
    ]
    assert messages[1].sender_name == "Fabien"
    assert messages[3].sender_url.endswith(SELF)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sent_at_never_falls_back_to_a_bare_clock_time():
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    with_urn = _event(OTHER, "bonjour", link="Fabien").replace(
        "</div></li>", '<time>11:27</time></div></li>'
    ).replace("2-bon", "2-MTc4OTM3ODA2OTg2NWI0NTkyMC0xMDAmOGNlMjA2OWE=")
    no_urn = '<li class="msg-s-event-listitem"><div class="msg-s-event-listitem__body">x<time>11:28</time></div></li>'
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(f"<ul>{with_urn}{no_urn}</ul>")
        messages = await MessagingScraper(page)._extract_messages("conv", limit=10)
        await browser.close()

    assert messages[0].sent_at == "2026-09-14T09:27:49.865000+00:00"
    assert messages[1].sent_at is None


def _bodyless_header(sender_id, name):
    return (
        '<li class="msg-s-event-listitem" data-event-urn="urn:li:msg_message:(x,2-att)">'
        f'<a class="msg-s-message-group__profile-link" href="/in/{sender_id}">'
        f'<span class="msg-s-message-group__name">{name}</span></a></li>'
    )


async def _extract(html):
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        messages = await MessagingScraper(page)._extract_messages("conv", limit=10)
        await browser.close()
    return messages


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bodyless_header_event_still_starts_the_new_group():
    # Pièce jointe seule (pas de corps) en tête du groupe de l'autre, puis son texte.
    html = "<ul>" + "".join(
        [
            _event(SELF, "hi", link="Vincent"),
            _bodyless_header(OTHER, "Fabien"),
            _event(OTHER, "mon cv please"),
        ]
    ) + "</ul>"
    messages = await _extract(html)

    assert [m.text for m in messages] == ["hi", "mon cv please"]
    assert messages[1].sender_name == "Fabien"
    assert messages[1].direction == "inbound"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_header_without_profile_link_does_not_inherit_the_previous_url():
    nameless_link = (
        '<li class="msg-s-event-listitem" data-event-urn="urn:li:msg_message:(x,2-abc)">'
        '<span class="msg-s-message-group__name">Acme Corp</span>'
        '<div class="msg-s-event-listitem__body">offre</div></li>'
    )
    html = "<ul>" + _event(OTHER, "bonjour", link="Fabien") + nameless_link + "</ul>"
    messages = await _extract(html)

    assert messages[1].sender_name == "Acme Corp"
    assert messages[1].sender_url is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_time_datetime_attribute_is_the_fallback_when_the_urn_has_no_epoch():
    html = (
        '<ul><li class="msg-s-event-listitem" data-event-urn="urn:li:msg_message:garbage">'
        '<div class="msg-s-event-listitem__body">x'
        '<time datetime="2026-10-11T08:00:00+00:00">08:00</time></div></li></ul>'
    )
    messages = await _extract(html)

    assert messages[0].sent_at == "2026-10-11T08:00:00+00:00"


async def _extract_limited(html, limit):
    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html)
        messages = await MessagingScraper(page)._extract_messages("conv", limit=limit)
        await browser.close()
    return messages


@pytest.mark.unit
@pytest.mark.asyncio
async def test_window_start_inherits_the_header_of_a_group_started_before_it():
    # Le groupe de Fabien commence avant la fenêtre `limit` : son 2e message,
    # premier de la fenêtre, n'a pas d'en-tête mais doit rester attribué à Fabien.
    html = "<ul>" + "".join(
        [
            _event(OTHER, "bonjour", link="Fabien"),
            _event(OTHER, "suite du groupe"),
            _event(SELF, "ma reponse", link="Vincent"),
        ]
    ) + "</ul>"
    messages = await _extract_limited(html, limit=2)

    assert [m.text for m in messages] == ["suite du groupe", "ma reponse"]
    assert messages[0].sender_name == "Fabien"
    assert messages[0].direction == "inbound"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_profile_link_inside_the_message_body_is_not_the_sender():
    # Le destinataire colle un lien /in/ de VINCENT dans le corps de son message
    # de continuation : ce lien ne doit ni devenir l'expéditeur ni inverser la direction.
    body_link = (
        f'<li class="msg-s-event-listitem" data-event-urn="urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-lnk)">'
        '<div class="msg-s-event-listitem__body">voici '
        f'<a href="https://www.linkedin.com/in/{SELF}">son profil</a></div></li>'
    )
    html = "<ul>" + _event(OTHER, "bonjour", link="Fabien") + body_link + "</ul>"
    messages = await _extract_limited(html, limit=10)

    assert messages[1].sender_name == "Fabien"
    assert messages[1].sender_url.endswith(OTHER)
    assert messages[1].direction == "inbound"


PROGRESSIVE_JS = """
(() => {
  const ul = document.querySelector('ul');
  const items = %s;
  items.forEach((html, i) => setTimeout(() => ul.insertAdjacentHTML('beforeend', html), 300 * i));
})()
"""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_thread_waits_until_events_stop_arriving():
    """Un fil rendu progressivement ne doit pas être lu à moitié (Cindy D., 2026-10-12)."""
    import json

    from playwright.async_api import async_playwright

    from linkedin_scraper.scrapers.messaging import MessagingScraper

    events = [
        _event(OTHER, "bonjour", link="Cindy"),
        _event(OTHER, "deuxieme"),
        _event(SELF, "reponse", link="Vincent"),
        _event(OTHER, "merci", link="Cindy"),
    ]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<ul></ul>")
        await page.evaluate(PROGRESSIVE_JS % json.dumps(events))
        scraper = MessagingScraper(page)
        await scraper._wait_for_thread_events()
        messages = await scraper._extract_messages("conv", limit=10)
        await browser.close()

    assert [m.text for m in messages] == ["bonjour", "deuxieme", "reponse", "merci"]
