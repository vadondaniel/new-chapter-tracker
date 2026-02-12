from scrapers import nicovideo_manga


class _MockResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise nicovideo_manga.requests.HTTPError(f"HTTP {self.status_code}")


def test_build_rss_url_from_comic_url():
    url = "https://manga.nicovideo.jp/comic/68937"
    assert (
        nicovideo_manga._build_rss_url(url)
        == "https://manga.nicovideo.jp/rss/manga/68937"
    )


def test_build_rss_url_from_existing_rss_url():
    url = "https://manga.nicovideo.jp/rss/manga/68937"
    assert nicovideo_manga._build_rss_url(url) == url


def test_scrape_reads_latest_item(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Series Title - Site Name</title>
    <item>
      <title>Series Title Episode 11-1</title>
      <link>https://manga.nicovideo.jp/watch/mg936718</link>
      <guid isPermaLink="false">dcf070a63bafcd11659b70589dd027f6</guid>
      <pubDate>Mon, 30 Jun 2025 11:00:00 +0900</pubDate>
    </item>
    <item>
      <title>Older Episode</title>
      <link>https://manga.nicovideo.jp/watch/mg856595</link>
      <pubDate>Sat, 07 Sep 2024 11:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""

    def fake_get(*args, **kwargs):
        return _MockResponse(xml)

    monkeypatch.setattr(nicovideo_manga.requests, "get", fake_get)

    chapter, timestamp, success, error, chapter_url = nicovideo_manga.scrape(
        "https://manga.nicovideo.jp/comic/68937"
    )

    assert chapter == "Episode 11-1"
    assert timestamp == "2025/06/30"
    assert success is True
    assert error is None
    assert chapter_url == "https://manga.nicovideo.jp/watch/mg936718"


def test_scrape_rejects_invalid_url():
    chapter, timestamp, success, error, chapter_url = nicovideo_manga.scrape(
        "https://manga.nicovideo.jp/watch/mg936718"
    )

    assert chapter == "No chapters found"
    assert isinstance(timestamp, str)
    assert success is False
    assert error == "Unable to parse comic ID from URL"
    assert chapter_url is None


def test_strip_series_prefix_keeps_original_when_prefix_missing():
    assert (
        nicovideo_manga._strip_series_prefix("Different Series Episode 1", "Series Title")
        == "Different Series Episode 1"
    )
