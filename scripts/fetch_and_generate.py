#!/usr/bin/env python3
"""
15歳までにみにつけた本当の学力 - 自動ニュース取得・記事生成スクリプト

処理フロー:
  1. RSS/APIからニュースを取得
  2. 教育・子ども関連のニュースをフィルタリング
  3. Claude APIで日本語要約・年齢分類・記事生成
  4. Jinja2テンプレートからHTML生成
  5. トップページ・各セクションページを更新
"""

import json
import os
import sys
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
from dateutil import parser as dateparser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# --- Paths ---
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
TEMPLATES = ROOT / "templates"
ARTICLES_DIR = ROOT / "articles" / "generated"

SOURCES_FILE = SCRIPTS / "sources.json"
ARTICLES_DB = DATA / "articles.json"

JST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 1. RSS取得
# ─────────────────────────────────────────────
def load_sources():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_rss_feeds(sources):
    """全RSSフィードからエントリを取得"""
    entries = []
    for feed_info in sources["rss_feeds"]:
        name = feed_info["name"]
        url = feed_info["url"]
        log.info(f"Fetching: {name}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                log.warning(f"  Failed to parse: {name} ({feed.bozo_exception})")
                continue
            for entry in feed.entries[:10]:
                published = None
                if hasattr(entry, "published"):
                    try:
                        published = dateparser.parse(entry.published).isoformat()
                    except Exception:
                        pass
                entries.append({
                    "source": name,
                    "category": feed_info["category"],
                    "language": feed_info.get("language", "en"),
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:500],
                    "published": published,
                    "id": hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()[:12],
                })
            log.info(f"  Got {min(len(feed.entries), 10)} entries")
        except Exception as e:
            log.warning(f"  Error fetching {name}: {e}")
    return entries


# ─────────────────────────────────────────────
# 2. フィルタリング・重複排除
# ─────────────────────────────────────────────
def load_existing_articles():
    if ARTICLES_DB.exists():
        with open(ARTICLES_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"articles": [], "last_updated": None}


def filter_new_entries(entries, existing):
    """既出のIDを除外"""
    known_ids = {a["id"] for a in existing.get("articles", [])}
    new = [e for e in entries if e["id"] not in known_ids]
    log.info(f"New entries after dedup: {len(new)} / {len(entries)}")
    return new


def is_education_relevant(entry, sources):
    """教育・子ども関連かどうか簡易判定"""
    text = (entry["title"] + " " + entry["summary"]).lower()
    all_keywords = []
    for kw_list in sources["keywords"].values():
        all_keywords.extend(kw_list)
    for kw_list in sources["pillar_keywords"].values():
        all_keywords.extend(kw_list)
    # 1つでもキーワードにヒットすれば通す
    return any(kw.lower() in text for kw in all_keywords)


def classify_age_group(entry, sources):
    """キーワードベースで対象年齢を推定"""
    text = (entry["title"] + " " + entry["summary"]).lower()
    scores = {}
    for age_key, keywords in sources["keywords"].items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[age_key] = score
    if not scores:
        return "all"
    return max(scores, key=scores.get)


def classify_pillar(entry, sources):
    """3本柱のどれに属するか"""
    text = (entry["title"] + " " + entry["summary"]).lower()
    scores = {}
    for pillar, keywords in sources["pillar_keywords"].items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[pillar] = score
    if not scores:
        return entry.get("category", "science")
    return max(scores, key=scores.get)


# ─────────────────────────────────────────────
# 3. Claude APIで記事生成
# ─────────────────────────────────────────────
def generate_article_with_ai(entry):
    """Claude APIを使って日本語記事を生成"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set - using fallback summary")
        return generate_fallback_article(entry)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    age_labels = {
        "age_0_2": "0〜2歳（乳児期）",
        "age_3_5": "3〜5歳（幼児期）",
        "age_6_9": "6〜9歳（学童前期）",
        "age_10_12": "10〜12歳（学童後期）",
        "age_13_15": "13〜15歳（思春期）",
        "all": "全年齢",
    }
    pillar_labels = {
        "science": "最新の科学",
        "skills": "社会が求める能力",
        "ai": "AI時代を生きる",
    }

    prompt = f"""以下のニュースを、教育ニュースサイト「15歳までにみにつけた本当の学力」の記事として日本語で書き直してください。

【元ニュース】
タイトル: {entry['title']}
概要: {entry['summary']}
出典: {entry['source']}
対象年齢: {age_labels.get(entry.get('age_group', 'all'), '全年齢')}
カテゴリ: {pillar_labels.get(entry.get('pillar', 'science'), '最新の科学')}

【出力形式（JSON）】
{{
  "headline": "日本語の記事タイトル（40字以内）",
  "subtitle": "サブタイトル（60字以内）",
  "excerpt": "要約（100字以内、トップページ表示用）",
  "body_html": "記事本文のHTML（h2, h3, p, blockquote, ulタグを使用。800〜1200字程度）",
  "key_points": ["ポイント1", "ポイント2", "ポイント3"],
  "parent_advice": "保護者へのアドバイス（150字以内）"
}}

【注意】
- 科学的根拠に基づいた正確な内容にしてください
- 保護者・教育者が読みやすい文体で
- 元の研究や出典は必ず明記してください
- JSON形式で出力してください"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # JSONを抽出（```json ... ``` 囲みがある場合も対応）
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        return json.loads(text.strip())
    except Exception as e:
        log.warning(f"AI generation failed: {e}")
        return generate_fallback_article(entry)


def generate_fallback_article(entry):
    """API未設定時のフォールバック"""
    title = entry["title"]
    summary = entry["summary"]
    # HTMLタグを除去
    import re
    summary = re.sub(r"<[^>]+>", "", summary)

    return {
        "headline": title[:40] if len(title) <= 40 else title[:37] + "...",
        "subtitle": f"{entry['source']}より",
        "excerpt": summary[:100] if len(summary) > 100 else summary,
        "body_html": f"<p>{summary}</p><p><strong>出典:</strong> <a href='{entry['link']}'>{entry['source']}</a></p>",
        "key_points": [summary[:50]],
        "parent_advice": "詳しくは元記事をご参照ください。",
    }


# ─────────────────────────────────────────────
# 4. HTML生成
# ─────────────────────────────────────────────
def render_article_page(article):
    """記事HTMLページを生成"""
    template_path = TEMPLATES / "article.html"
    if not template_path.exists():
        log.warning("Article template not found, skipping HTML generation")
        return None

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    template = env.get_template("article.html")

    html = template.render(
        article=article,
        generated_date=datetime.now(JST).strftime("%Y.%m.%d"),
        year=datetime.now(JST).year,
    )
    return html


def render_index_page(articles, sources):
    """トップページを最新記事で更新"""
    template_path = TEMPLATES / "index.html"
    if not template_path.exists():
        log.info("Index template not found, skipping index update")
        return None

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    template = env.get_template("index.html")

    # 最新10件
    recent = sorted(articles, key=lambda a: a.get("published") or "", reverse=True)[:10]
    # 柱別
    by_pillar = {
        "science": [a for a in recent if a.get("pillar") == "science"][:4],
        "skills": [a for a in recent if a.get("pillar") == "skills"][:4],
        "ai": [a for a in recent if a.get("pillar") == "ai"][:4],
    }

    html = template.render(
        articles=recent,
        by_pillar=by_pillar,
        generated_date=datetime.now(JST).strftime("%Y年%m月%d日"),
        year=datetime.now(JST).year,
        total_articles=len(articles),
    )
    return html


# ─────────────────────────────────────────────
# 5. メイン処理
# ─────────────────────────────────────────────
def main():
    log.info("=== 15歳までにみにつけた本当の学力 - 自動更新開始 ===")

    # ディレクトリ作成
    DATA.mkdir(exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    # ソース読み込み
    sources = load_sources()
    existing = load_existing_articles()

    # RSS取得
    entries = fetch_rss_feeds(sources)
    if not entries:
        log.warning("No entries fetched from any source")
        sys.exit(0)

    # フィルタ・分類
    new_entries = filter_new_entries(entries, existing)
    relevant = [e for e in new_entries if is_education_relevant(e, sources)]
    log.info(f"Education-relevant entries: {len(relevant)}")

    if not relevant:
        log.info("No new relevant articles today")
        sys.exit(0)

    # 年齢・柱の分類
    for entry in relevant:
        entry["age_group"] = classify_age_group(entry, sources)
        entry["pillar"] = classify_pillar(entry, sources)

    # 記事数制限（1日最大5記事）
    to_process = relevant[:5]
    log.info(f"Processing {len(to_process)} articles")

    # AI生成 & HTML出力
    generated_articles = []
    for i, entry in enumerate(to_process):
        log.info(f"[{i+1}/{len(to_process)}] Generating: {entry['title'][:50]}...")

        ai_content = generate_article_with_ai(entry)

        article = {
            **entry,
            **ai_content,
            "generated_at": datetime.now(JST).isoformat(),
            "slug": entry["id"],
        }

        # 記事ページ生成
        html = render_article_page(article)
        if html:
            output_path = ARTICLES_DIR / f"{article['slug']}.html"
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            log.info(f"  Wrote: {output_path.name}")

        generated_articles.append(article)

    # DB更新
    all_articles = existing.get("articles", []) + generated_articles
    db = {
        "articles": all_articles,
        "last_updated": datetime.now(JST).isoformat(),
        "total_count": len(all_articles),
    }
    with open(ARTICLES_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    log.info(f"Database updated: {len(all_articles)} total articles")

    # トップページ更新
    index_html = render_index_page(all_articles, sources)
    if index_html:
        with open(ROOT / "index.html", "w", encoding="utf-8") as f:
            f.write(index_html)
        log.info("Index page updated")

    log.info("=== 自動更新完了 ===")
    log.info(f"  新規記事: {len(generated_articles)}件")
    log.info(f"  合計記事: {len(all_articles)}件")


if __name__ == "__main__":
    main()
