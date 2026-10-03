import types

import clickbot


class FakeLink:
    def __init__(self, href):
        self.href = href

    def get_attribute(self, name):
        if name == "href":
            return self.href
        if name == "data-rw":
            return self.href
        return None


class FakeDriver:
    def __init__(self, links):
        self._links = links
        self.current_window_handle = "main"
        self.window_handles = {"main"}

    def find_elements(self, by, selector):
        return self._links if selector in {"a.sVXRqc", "a.taydad", "a.tNxQIb", "a[data-rw]", "a[href*='/aclk?']", "a[href]", "[role='link']"} else []

    def back(self):
        return None

    def switch_to(self, *args, **kwargs):
        class SwitchTo:
            def window(self, *_args, **_kwargs):
                return None
        return SwitchTo()


def test_find_live_ad_link_by_href_uses_live_dom(monkeypatch):
    live_href = "https://www.google.com/aclk?sa=L&id=second"
    stale_link = FakeLink(live_href)
    fresh_link = FakeLink(live_href)
    driver = FakeDriver([fresh_link])
    logger = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)

    monkeypatch.setattr(clickbot, "human_scroll", lambda *a, **k: None)
    monkeypatch.setattr(clickbot, "human_move_and_click", lambda *a, **k: None)
    monkeypatch.setattr(clickbot.time, "sleep", lambda *a, **k: None)

    live = clickbot._find_live_ad_link_by_href(driver, stale_link.href, logger=logger)
    assert live is not None
    assert live.href == fresh_link.href

    monkeypatch.setattr(clickbot, "_find_live_ad_link_by_href", lambda d, href, logger=None: fresh_link)
    monkeypatch.setattr(clickbot, "human_move_and_click", lambda d, el: None)

    res = clickbot.click_ad(driver, stale_link, stale_link.href, {"behavior": {}}, logger)
    assert res is True
