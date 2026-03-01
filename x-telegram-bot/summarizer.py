import asyncio
import logging
import re
from html import escape
import httpx
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from x_client import Tweet

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RETRIES = 3


async def summarize_tweets(username: str, tweets: list[Tweet]) -> str:
    """Summarize tweets with original summary + commentary format."""
    if not tweets:
        return f"X:{username}의 최근 24시간 트윗이 없습니다."

    if not OPENROUTER_API_KEY:
        return "Error: OPENROUTER_API_KEY가 설정되지 않았습니다."

    # Build tweet index map for post-processing
    url_map: dict[int, str] = {}
    tweet_texts = []
    for i, t in enumerate(tweets, 1):
        url_map[i] = t.url
        line = f"[트윗#{i}] {t.text}"
        if t.quoted_tweet:
            line += f"\n   (인용: {t.quoted_tweet.text[:200]})"
        tweet_texts.append(line)

    all_tweets_text = "\n\n".join(tweet_texts)

    prompt = (
        f"다음은 X(Twitter) 계정 X:{username}의 최근 24시간 트윗 {len(tweets)}개입니다.\n\n"
        f"{all_tweets_text}\n\n"
        f"위 트윗들을 아래 형식으로 정리해주세요. 텔레그램 메시지로 보내질 것이므로 깔끔하고 읽기 쉽게 작성해주세요.\n\n"
        f"=== 출력 형식 ===\n\n"
        f"주제별로 묶어서 아래 형식을 반복:\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 주제 제목\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▶ 요약\n"
        f"해당 트윗의 원문 핵심 내용을 간결하게 정리.\n\n"
        f"💡 해설\n"
        f"이 내용이 왜 중요한지, 맥락/배경/시장 영향 등을 1~3문장으로 해설.\n\n"
        f"출처: REF1, REF3\n"
        f"(REF 뒤의 숫자는 해당 트윗 번호. 반드시 REF + 숫자 형식만 사용)\n\n"
        f"=== 규칙 ===\n"
        f"1. 계정명에 '@' 기호 절대 사용 금지. 반드시 'X:계정명' 형식 사용\n"
        f"2. 출처는 반드시 'REF1', 'REF2' 등 형식으로만 표기\n"
        f"3. URL이나 링크를 절대 직접 쓰지 말 것. 오직 REF + 숫자만 사용\n"
        f"4. 이모지(📎🔗 등)를 출처 앞에 붙이지 말 것. 그냥 '출처: REF1' 으로만\n"
        f"5. 리트윗이면 누구의 글인지 'X:원작성자' 형식으로 표시\n"
        f"6. 마지막에 구분선 후 '📊 오늘의 톤: ...' 으로 전체 분위기 한줄 요약\n"
        f"7. 마크다운(**, ##, [] 등) 사용하지 말고 이모지+텍스트로만 구성\n"
        f"8. 한국어로 작성"
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that summarizes and analyzes X(Twitter) tweets in Korean. Output must be clean plain text with emojis for Telegram. Never use '@' before usernames — always use 'X:username' format. Never use markdown syntax. For source references, ONLY use REF1, REF2 etc. Never write URLs directly."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = None
        for attempt in range(1, MAX_RETRIES + 1):
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            if resp.status_code == 200:
                break
            logger.warning("OpenRouter attempt %d/%d failed: %d %s", attempt, MAX_RETRIES, resp.status_code, resp.text[:200])
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3 * attempt)

        if resp.status_code != 200:
            return f"요약 API 오류: {resp.status_code} — {resp.text[:200]}"

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Safety: replace any remaining @ mentions
        content = content.replace("@", "X:")

        # Strip any raw URLs the AI might have included
        content = re.sub(r'\(?https?://x\.com/\S+\)?', '', content)

        # HTML escape the entire content (for Telegram HTML parse mode)
        content = escape(content)

        # Replace REF references with clickable hyperlinks
        def _replace_ref(match):
            num = int(match.group(1))
            url = url_map.get(num)
            if url:
                return f'<a href="{url}">원문보기</a>'
            return match.group(0)

        content = re.sub(r'REF(\d+)', _replace_ref, content)

        # Clean up: remove leftover "출처:" label lines that are now just whitespace
        content = re.sub(r'출처:\s*\n', '\n', content)

        return content.strip()

    except Exception as e:
        logger.error("Summarization failed: %s", e)
        return f"요약 중 오류 발생: {e}"
