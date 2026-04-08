import os
import re
import sys
import time
import html
from datetime import datetime
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
import schedule
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "20"))
NEWS_LIMIT = int(os.getenv("NEWS_LIMIT", "8"))
REFERENCE_LINK_LIMIT = int(os.getenv("REFERENCE_LINK_LIMIT", "3"))
TEST_MODE = os.getenv("TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
CUSTOM_WATCHLIST = os.getenv("CUSTOM_WATCHLIST", "").strip()

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)

DAY_NAME_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

TASK = {
    "name": "us_market_close_briefing",
    "label": "미국증시 마감 브리핑",
    "time": os.getenv("US_CLOSE_BRIEF_TIME", "06:30"),
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "exclude_weekends": False,
    "max_retries": 3,
}

INDEX_SYMBOLS = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow": "^DJI",
    "Russell 2000": "^RUT",
@@ -57,100 +60,215 @@ MEGA_CAP_SYMBOLS = {
    "Microsoft": "MSFT",
    "Apple": "AAPL",
    "Amazon": "AMZN",
    "Alphabet": "GOOGL",
    "Meta": "META",
    "Tesla": "TSLA",
    "Broadcom": "AVGO",
    "Berkshire Hathaway": "BRK-B",
    "JPMorgan": "JPM",
}

SECTOR_SYMBOLS = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Financials": "XLF",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Semiconductors": "SOXX",
    "Software": "IGV",
    "Biotech": "XBI",
    "Banks": "KBE",
    "Regional Banks": "KRE",
    "Cybersecurity": "HACK",
    "Cloud Computing": "SKYY",
    "AI & Robotics": "BOTZ",
    "Clean Energy": "ICLN",
    "Homebuilders": "XHB",
    "Aerospace & Defense": "ITA",
    "U.S. Infrastructure": "PAVE",
    "Oil & Gas Exploration": "XOP",
    "Gold Miners": "GDX",
}

CNBC_RSS_URLS = [
    "https://www.cnbc.com/markets/?format=rss",
    "https://www.cnbc.com/investing/?format=rss",
    "https://www.cnbc.com/?format=rss",
]

INVESTING_RSS_URLS = [
    "https://www.investing.com/rss/news_285.rss",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/market_overview.rss",
]

ALT_NEWS_RSS_SOURCES = {
    "Reuters Markets": [
        "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    ],
    "MarketWatch Top Stories": [
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    ],
    "Yahoo Finance": [
        "https://finance.yahoo.com/news/rssindex",
    ],
}

NEWS_BLOCKLIST_PATTERNS = [
    r"\bvideo\b",
    r"\bpodcast\b",
    r"\badvertis",
    r"\bsponsored\b",
    r"\bnewsletter\b",
]


def validate_env() -> None:
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise ValueError(f".env 누락 항목: {', '.join(missing)}")


def validate_task() -> None:
    required_keys = ["name", "label", "time", "days", "exclude_weekends"]
    for key in required_keys:
        if key not in TASK:
            raise ValueError(f"TASK 설정 누락: key={key}")

    for day in TASK["days"]:
        if day not in DAY_NAME_MAP:
            raise ValueError(f"TASK 요일 값 오류: {day}")

    if ":" not in TASK["time"]:
        raise ValueError(f"TASK time 형식 오류: {TASK['time']} (예: 06:30)")


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + (n - 1) * 7)


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    shift = (last.weekday() - weekday) % 7
    return last - timedelta(days=shift)


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    d = date(year, month, day)
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def get_easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_us_market_holidays(year: int) -> set[date]:
    holidays = set()
    holidays.add(observed_fixed_holiday(year, 1, 1))  # New Year's Day
    holidays.add(nth_weekday_of_month(year, 1, 0, 3))  # MLK Day
    holidays.add(nth_weekday_of_month(year, 2, 0, 3))  # Washington's Birthday
    holidays.add(get_easter_date(year) - timedelta(days=2))  # Good Friday
    holidays.add(last_weekday_of_month(year, 5, 0))  # Memorial Day
    holidays.add(observed_fixed_holiday(year, 6, 19))  # Juneteenth
    holidays.add(observed_fixed_holiday(year, 7, 4))  # Independence Day
    holidays.add(nth_weekday_of_month(year, 9, 0, 1))  # Labor Day
    holidays.add(nth_weekday_of_month(year, 11, 3, 4))  # Thanksgiving
    holidays.add(observed_fixed_holiday(year, 12, 25))  # Christmas
    return holidays


def is_us_market_holiday(target_date: date) -> bool:
    return target_date in get_us_market_holidays(target_date.year)


def is_task_day(task: dict, dt: datetime | None = None) -> bool:
    dt = dt or datetime.now()
    if TEST_MODE:
        return True

    weekday = dt.weekday()
    if task.get("exclude_weekends", False) and weekday >= 5:
        return False
    if is_us_market_holiday(dt.date()):
        return False
    allowed_days = [DAY_NAME_MAP[d] for d in task["days"]]
    return weekday in allowed_days


def parse_custom_watchlist() -> dict[str, str]:
    if not CUSTOM_WATCHLIST:
        return {}

    output = {}
    tokens = [x.strip() for x in CUSTOM_WATCHLIST.split(",") if x.strip()]
    for token in tokens:
        if ":" in token:
            name, symbol = token.split(":", 1)
            output[normalize_text(name)] = normalize_text(symbol).upper()
        else:
            normalized = normalize_text(token).upper()
            output[normalized] = normalized
    return output


def normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def fetch_json(url: str, params: dict | None = None, timeout: int = 30) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; USCloseBriefBot/1.0)"}
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_text(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; USCloseBriefBot/1.0)"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def get_yahoo_chart_snapshot(symbol: str) -> dict:
    encoded_symbol = quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
    params = {
        "interval": "1d",
        "range": "5d",
        "includePrePost": "false",
@@ -256,95 +374,132 @@ def collect_top_movers() -> dict:
    except Exception as e:
        print(f"[WARN] Alpha Vantage TOP_GAINERS_LOSERS 수집 실패 / {e}")
        return {}


def parse_rss_items(xml_text: str, source_name: str) -> list[dict]:
    items = []
    root = ET.fromstring(xml_text)

    for item in root.findall(".//item"):
        title = normalize_text(item.findtext("title", default=""))
        link = normalize_text(item.findtext("link", default=""))
        description = normalize_text(item.findtext("description", default=""))
        if not title or not link:
            continue
        items.append({
            "title": title,
            "link": link,
            "summary": description[:280],
            "source": source_name,
        })

    return items


def is_high_quality_news(item: dict) -> bool:
    title = normalize_text(item.get("title", ""))
    summary = normalize_text(item.get("summary", ""))
    link = normalize_text(item.get("link", ""))
    lowered = f"{title} {summary}".lower()

    if len(title) < 25:
        return False
    if len(link) < 10 or not link.startswith("http"):
        return False
    if any(re.search(pattern, lowered) for pattern in NEWS_BLOCKLIST_PATTERNS):
        return False
    return True


def dedupe_news(items: list[dict]) -> list[dict]:
    seen = set()
    seen_titles = set()
    out = []
    for item in items:
        key = item["link"].strip().lower()
        if not key or key in seen:
        title_key = re.sub(r"[^a-z0-9]+", " ", item["title"].strip().lower())
        if not key or key in seen or title_key in seen_titles:
            continue
        if not is_high_quality_news(item):
            continue
        seen.add(key)
        seen_titles.add(title_key)
        out.append(item)
    return out


def collect_cnbc_rss_news() -> list[dict]:
    collected = []
    for url in CNBC_RSS_URLS:
        try:
            xml_text = fetch_text(url, timeout=30)
            collected.extend(parse_rss_items(xml_text, "CNBC"))
        except Exception as e:
            print(f"[WARN] CNBC RSS 수집 실패: {url} / {e}")

    return dedupe_news(collected)[:NEWS_LIMIT]


def collect_investing_rss_news() -> list[dict]:
    collected = []
    for url in INVESTING_RSS_URLS:
        try:
            xml_text = fetch_text(url, timeout=30)
            collected.extend(parse_rss_items(xml_text, "Investing.com"))
        except Exception as e:
            print(f"[WARN] Investing RSS 수집 실패: {url} / {e}")

    return dedupe_news(collected)[:NEWS_LIMIT]


def collect_alt_rss_news() -> list[dict]:
    collected = []
    for source_name, urls in ALT_NEWS_RSS_SOURCES.items():
        for url in urls:
            try:
                xml_text = fetch_text(url, timeout=30)
                collected.extend(parse_rss_items(xml_text, source_name))
            except Exception as e:
                print(f"[WARN] 대체 RSS 수집 실패: {source_name} / {url} / {e}")

    return dedupe_news(collected)[:NEWS_LIMIT]


def collect_news() -> list[dict]:
    av_news = collect_alpha_vantage_news()
    if av_news:
        return av_news[:NEWS_LIMIT]

    cnbc_news = collect_cnbc_rss_news()
    if cnbc_news:
        return cnbc_news[:NEWS_LIMIT]

    alt_news = collect_alt_rss_news()
    if alt_news:
        return alt_news[:NEWS_LIMIT]

    investing_news = collect_investing_rss_news()
    return investing_news[:NEWS_LIMIT]


def format_market_block(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        sign = "+" if row["pct"] >= 0 else ""
        lines.append(f"- {row['name']}: {row['price']:.2f} ({sign}{row['pct']:.2f}%)")
    return "\n".join(lines)


def format_sorted_sector_block(rows: list[dict], reverse: bool) -> str:
    sorted_rows = sorted(rows, key=lambda x: x["pct"], reverse=reverse)
    top = sorted_rows[:4]
    lines = []
    for row in top:
        sign = "+" if row["pct"] >= 0 else ""
        lines.append(f"- {row['name']}: {sign}{row['pct']:.2f}%")
    return "\n".join(lines)


def format_top_movers_block(data: dict) -> str:
    if not data:
        return ""
@@ -372,293 +527,353 @@ def format_top_movers_block(data: dict) -> str:
                lines.append(f"- {ticker}: {change_pct}")

    if active:
        lines.append("[MOST ACTIVE]")
        for x in active:
            ticker = normalize_text(x.get("ticker", ""))
            volume = normalize_text(str(x.get("volume", "")))
            if ticker:
                lines.append(f"- {ticker}: volume={volume}")

    return "\n".join(lines)


def format_news_block(items: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(items[:NEWS_LIMIT], start=1):
        lines.append(
            f"[{idx}] SOURCE={item['source']}\n"
            f"TITLE={item['title']}\n"
            f"LINK={item['link']}\n"
            f"SUMMARY={item['summary']}\n"
        )
    return "\n".join(lines)


def build_prompt(index_rows: list[dict], mega_rows: list[dict], sector_rows: list[dict], news_items: list[dict], top_movers: dict) -> str:
def build_prompt(
    index_rows: list[dict],
    mega_rows: list[dict],
    sector_rows: list[dict],
    news_items: list[dict],
    top_movers: dict,
    custom_rows: list[dict],
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    return f"""
오늘 날짜는 {today} 입니다.

당신의 역할:
- 미국 주식 마감 브리핑 에디터
- 텔레그램에서 1분 안에 읽히는 짧고 깔끔한 메시지 작성
- 뉴스 요약이 아니라 "자금 흐름 + 핵심 종목 변화 + 다음 체크포인트"를 해석

아래는 실제 자동 수집한 마감 데이터와 뉴스입니다.
반드시 아래 자료만 근거로 작성하세요.
링크를 새로 만들거나 추측하지 마세요.

[자동 수집 지수 데이터]
{format_market_block(index_rows)}

[자동 수집 시총 상위 종목 데이터]
{format_market_block(mega_rows)}

[자동 수집 사용자 커스텀 종목 데이터]
{format_market_block(custom_rows) if custom_rows else "- 없음"}

[자동 수집 섹터/산업 데이터 - 강한 순 참고]
{format_sorted_sector_block(sector_rows, reverse=True)}

[자동 수집 섹터/산업 데이터 - 약한 순 참고]
{format_sorted_sector_block(sector_rows, reverse=False)}

[자동 수집 상·하락 보강 데이터]
{format_top_movers_block(top_movers)}

[자동 수집 뉴스]
{format_news_block(news_items)}

출력 형식:
📌 미국증시 마감 브리핑 ({today})

<b>한 줄 총평</b>
- 한 문장

<b>지수</b>
- 2~3줄
- 숫자 나열보다 해석 우선
- 예: 나스닥 우위 / 대형주 강세 / 중소형주 부진

<b>자금 흐름</b>
- 3개
- 어디로 돈이 들어가고 빠졌는지
- 짧고 단정하게

<b>핵심 종목</b>
- 5~6개
- 형식: 종목명: 강세/약세 + 이유
- 한 줄씩 짧게

<b>커스텀 종목 브리핑</b>
- custom 종목이 있다면 2~5개를 별도 bullet로 요약
- 형식: 종목명: 당일 흐름 + 체크포인트
- custom 종목이 없으면 이 섹션은 생략

<b>강한 곳 / 약한 곳</b>
- 강한 섹터·산업: 2~3개
- 약한 섹터·산업: 2~3개

<b>체크포인트</b>
- 2~3개
- 다음 장에서 볼 포인트만 적기

<b>참고 링크</b>
- {REFERENCE_LINK_LIMIT}개 이내
- 형식: - <a href="실제링크">짧은 제목</a>

문장 규칙:
- 텔레그램용으로 작성한다.
- 문장은 짧고 명확하게 쓴다.
- 모바일에서 읽기 좋도록 줄바꿈을 깔끔하게 넣고, 줄을 가지런히 맞춘다.
- 각 bullet은 가능하면 1~2줄 이내로 유지한다.
- 불필요한 서론은 넣지 않는다.
- 같은 표현을 반복하지 않는다.
- 과장된 표현, 감탄문, 불필요한 이모지는 쓰지 않는다.
- 이모지는 제목의 📌 1개만 사용한다.
- 전체 톤은 차분하고 전문적인 시장 메모처럼 유지한다.
- 링크는 실제 수집한 링크만 사용한다.
- 근거가 부족한 내용은 쓰지 않는다.
- 숫자는 확인 가능한 범위에서만 간단히 반영하고, 해석을 우선한다.
- 최종 결과는 짧고 압축된 브리핑처럼 보이게 정리한다.
""".strip()


def generate_analysis(index_rows: list[dict], mega_rows: list[dict], sector_rows: list[dict], news_items: list[dict], top_movers: dict) -> str:
    prompt = build_prompt(index_rows, mega_rows, sector_rows, news_items, top_movers)
def generate_analysis(
    index_rows: list[dict],
    mega_rows: list[dict],
    sector_rows: list[dict],
    news_items: list[dict],
    top_movers: dict,
    custom_rows: list[dict],
) -> str:
    prompt = build_prompt(index_rows, mega_rows, sector_rows, news_items, top_movers, custom_rows)
    response = client.responses.create(model=OPENAI_MODEL, input=prompt)
    text = getattr(response, "output_text", "") or ""
    text = text.strip()
    if not text:
        raise RuntimeError("OpenAI 응답이 비어 있습니다.")
    return text


def build_fallback_message(index_rows: list[dict], mega_rows: list[dict], sector_rows: list[dict], news_items: list[dict]) -> str:
def build_fallback_message(
    index_rows: list[dict],
    mega_rows: list[dict],
    sector_rows: list[dict],
    news_items: list[dict],
    custom_rows: list[dict],
) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    strong = sorted(sector_rows, key=lambda x: x["pct"], reverse=True)[:3]
    weak = sorted(sector_rows, key=lambda x: x["pct"])[:3]
    key_names = ["NVIDIA", "Microsoft", "Apple", "Amazon", "Alphabet", "Meta", "Tesla"]

    mega_map = {x["name"]: x for x in mega_rows}

    lines = [f"📌 미국증시 마감 브리핑 ({today})", ""]

    lines.append("<b>지수</b>")
    for row in index_rows:
        sign = "+" if row["pct"] >= 0 else ""
        lines.append(f"- {row['name']}: {sign}{row['pct']:.2f}%")
    lines.append("")

    if custom_rows:
        lines.append("<b>커스텀 종목 브리핑</b>")
        for row in custom_rows[:5]:
            sign = "+" if row["pct"] >= 0 else ""
            lines.append(f"- {row['name']}: {sign}{row['pct']:.2f}%")
        lines.append("")

    lines.append("<b>핵심 종목</b>")
    for name in key_names:
        row = mega_map.get(name)
        if not row:
            continue
        sign = "+" if row["pct"] >= 0 else ""
        lines.append(f"- {name}: {sign}{row['pct']:.2f}%")
    lines.append("")

    lines.append("<b>강한 곳 / 약한 곳</b>")
    lines.append("- 강한: " + ", ".join([f"{x['name']}({x['pct']:+.2f}%)" for x in strong]))
    lines.append("- 약한: " + ", ".join([f"{x['name']}({x['pct']:+.2f}%)" for x in weak]))
    lines.append("")

    if news_items:
        lines.append("<b>참고 링크</b>")
        for item in news_items[:REFERENCE_LINK_LIMIT]:
            title = html.escape(item["title"])
            link = html.escape(item["link"], quote=True)
            lines.append(f'- <a href="{link}">{title}</a>')

    return "\n".join(lines)


def split_message(text: str, limit: int = 3500) -> list[str]:
    chunks = []
    remaining = text.strip()

    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def style_message_html(message: str) -> str:
    section_map = {
        "<b>한 줄 총평</b>": "<b>🧭 한 줄 총평</b>",
        "<b>지수</b>": "<b>📈 지수</b>",
        "<b>자금 흐름</b>": "<b>💸 자금 흐름</b>",
        "<b>핵심 종목</b>": "<b>🏷️ 핵심 종목</b>",
        "<b>커스텀 종목 브리핑</b>": "<b>🎯 커스텀 종목 브리핑</b>",
        "<b>강한 곳 / 약한 곳</b>": "<b>🧩 강한 곳 / 약한 곳</b>",
        "<b>체크포인트</b>": "<b>✅ 체크포인트</b>",
        "<b>참고 링크</b>": "<b>🔗 참고 링크</b>",
    }
    styled = message
    for plain, iconed in section_map.items():
        styled = styled.replace(plain, iconed)

    styled = styled.replace("- ", "• ")
    return styled


def send_to_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chunk in split_message(message):
    styled_message = style_message_html(message)

    for chunk in split_message(styled_message):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        response = requests.post(url, json=payload, timeout=30)
        print("TELEGRAM STATUS:", response.status_code)
        print("TELEGRAM BODY:", response.text)
        response.raise_for_status()


def save_log(task_name: str, content: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = LOG_DIR / f"{task_name}_{timestamp}.txt"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def save_error_log(task_name: str, error_message: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d")
    error_log = LOG_DIR / f"error_{task_name}_{timestamp}.txt"
    with open(error_log, "a", encoding="utf-8") as f:
        f.write(error_message + "\n")
    return error_log


def collect_all_data() -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
def collect_all_data() -> tuple[list[dict], list[dict], list[dict], list[dict], dict, list[dict]]:
    index_rows = collect_symbol_group(INDEX_SYMBOLS)
    mega_rows = collect_symbol_group(MEGA_CAP_SYMBOLS)
    sector_rows = collect_symbol_group(SECTOR_SYMBOLS)
    custom_rows = collect_symbol_group(parse_custom_watchlist())
    news_items = collect_news()
    top_movers = collect_top_movers()

    if not index_rows:
        raise RuntimeError("지수 데이터 수집 실패")
    if not mega_rows:
        raise RuntimeError("대표 종목 데이터 수집 실패")
    if not sector_rows:
        raise RuntimeError("섹터 데이터 수집 실패")

    return index_rows, mega_rows, sector_rows, news_items, top_movers
    return index_rows, mega_rows, sector_rows, news_items, top_movers, custom_rows


def execute_task(task: dict) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] task 시작: {task['name']}")

    if not is_task_day(task):
        print(f"오늘은 task[{task['name']}] 발송 대상 요일이 아닙니다. 건너뜁니다.")
        if is_us_market_holiday(datetime.now().date()):
            print(f"오늘은 미국 증시 휴장일입니다. task[{task['name']}]를 건너뜁니다.")
        else:
            print(f"오늘은 task[{task['name']}] 발송 대상 요일이 아닙니다. 건너뜁니다.")
        return

    retries = task.get("max_retries", MAX_RETRIES)
    attempt = 0

    while attempt < retries:
        attempt += 1
        try:
            print("시장 데이터 및 뉴스 수집 시작")
            index_rows, mega_rows, sector_rows, news_items, top_movers = collect_all_data()
            index_rows, mega_rows, sector_rows, news_items, top_movers, custom_rows = collect_all_data()
            print("데이터 수집 완료")

            analysis = generate_analysis(index_rows, mega_rows, sector_rows, news_items, top_movers)
            analysis = generate_analysis(index_rows, mega_rows, sector_rows, news_items, top_movers, custom_rows)
            print("=== GENERATED ANALYSIS ===")
            print(analysis)

            log_path = save_log(task["name"], analysis)
            print(f"로그 저장 완료: {log_path}")

            send_to_telegram(analysis)
            print(f"텔레그램 전송 완료: {task['name']}")
            return

        except Exception as e:
            error_text = (
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"task={task['name']} attempt={attempt}/{retries} 오류: {e}"
            )
            print(error_text)
            error_log_path = save_error_log(task["name"], error_text)
            print(f"에러 로그 저장 완료: {error_log_path}")

            if attempt == retries:
                try:
                    index_rows, mega_rows, sector_rows, news_items, _ = collect_all_data()
                    fallback_message = build_fallback_message(index_rows, mega_rows, sector_rows, news_items)
                    index_rows, mega_rows, sector_rows, news_items, _, custom_rows = collect_all_data()
                    fallback_message = build_fallback_message(index_rows, mega_rows, sector_rows, news_items, custom_rows)
                    send_to_telegram(fallback_message)
                    print(f"fallback 전송 완료: {task['name']}")
                    return
                except Exception as fallback_error:
                    fallback_error_text = (
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"task={task['name']} fallback 오류: {fallback_error}"
                    )
                    print(fallback_error_text)
                    save_error_log(task["name"], fallback_error_text)

            if attempt < retries:
                print(f"{RETRY_DELAY_SECONDS}초 후 재시도합니다.")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                print(f"task[{task['name']}] 최종 실패")


def run_now_mode() -> None:
    print("실행 모드: 즉시 실행")
    execute_task(TASK)


def register_schedule_jobs() -> None:
    schedule.clear()
