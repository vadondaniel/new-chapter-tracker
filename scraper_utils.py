import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def needs_update(url, previous_data, max_days, force_update):
    if force_update or url not in previous_data:
        return True
    last_ts = previous_data[url]["timestamp"]
    last_date = datetime.datetime.strptime(last_ts, "%Y/%m/%d")
    return (datetime.datetime.now() - last_date).days > max_days


def parse_timestamp(date_str, fmt="%Y-%m-%d"):
    return datetime.datetime.strptime(date_str[:10], fmt).strftime("%Y/%m/%d")


def convert_to_rss_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = ["rss"]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )
