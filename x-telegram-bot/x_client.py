import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import httpx

from config import X_BEARER_TOKEN, X_GRAPHQL_USER_BY_SCREEN_NAME, X_GRAPHQL_USER_TWEETS
from cookie_manager import get_x_cookies, invalidate_cache, validate_cookies

logger = logging.getLogger(__name__)

BASE = "https://x.com/i/api/graphql"


@dataclass
class Tweet:
    id: str
    text: str
    created_at: str
    url: str
    media_urls: list[str] = field(default_factory=list)
    is_retweet: bool = False
    quoted_tweet: "Tweet | None" = None


class XClientError(Exception):
    pass


class XClient:
    def __init__(self) -> None:
        self._user_id_cache: dict[str, str] = {}

    def _headers(self, cookies: dict[str, str]) -> dict[str, str]:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "authorization": f"Bearer {X_BEARER_TOKEN}",
            "x-csrf-token": cookies.get("ct0", ""),
            "cookie": cookie_str,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "content-type": "application/json",
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "referer": "https://x.com/",
        }

    async def _request(self, url: str, params: dict | None = None, retry: bool = True) -> dict:
        cookies = get_x_cookies()
        ok, msg = validate_cookies(cookies)
        if not ok:
            raise XClientError(msg)

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=self._headers(cookies), params=params)

        if resp.status_code in (401, 403) and retry:
            logger.info("Got %s, refreshing cookies and retrying…", resp.status_code)
            invalidate_cache()
            return await self._request(url, params, retry=False)

        if resp.status_code != 200:
            raise XClientError(f"X API returned {resp.status_code}: {resp.text[:300]}")

        return resp.json()

    async def get_user_id(self, screen_name: str) -> str:
        screen_name = screen_name.lstrip("@")
        if screen_name in self._user_id_cache:
            return self._user_id_cache[screen_name]

        variables = json.dumps({
            "screen_name": screen_name,
            "withSafetyModeUserFields": True,
        })
        features = json.dumps({
            "hidden_profile_subscriptions_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        })

        data = await self._request(
            f"{BASE}/{X_GRAPHQL_USER_BY_SCREEN_NAME}",
            params={"variables": variables, "features": features},
        )

        try:
            user_id = data["data"]["user"]["result"]["rest_id"]
        except (KeyError, TypeError) as e:
            raise XClientError(f"Cannot resolve user @{screen_name}: {e}") from e

        self._user_id_cache[screen_name] = user_id
        return user_id

    async def get_user_tweets(self, screen_name: str, count: int = 5) -> list[Tweet]:
        user_id = await self.get_user_id(screen_name)

        variables = json.dumps({
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        })
        features = json.dumps({
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        })

        data = await self._request(
            f"{BASE}/{X_GRAPHQL_USER_TWEETS}",
            params={"variables": variables, "features": features},
        )

        return self._parse_timeline(data, screen_name)

    async def get_tweets_last_24h(self, screen_name: str) -> list[Tweet]:
        """Fetch tweets from the last 24 hours. Fetches up to 50 and filters by time."""
        tweets = await self.get_user_tweets(screen_name, count=50)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent: list[Tweet] = []
        for t in tweets:
            try:
                # X date format: "Mon Feb 24 10:00:00 +0000 2026"
                dt = datetime.strptime(t.created_at, "%a %b %d %H:%M:%S %z %Y")
                if dt >= cutoff:
                    recent.append(t)
            except (ValueError, TypeError):
                recent.append(t)  # include if we can't parse the date
        return recent

    def _parse_timeline(self, data: dict, screen_name: str) -> list[Tweet]:
        tweets: list[Tweet] = []
        try:
            instructions = data["data"]["user"]["result"]["timeline_v2"]["timeline"]["instructions"]
        except (KeyError, TypeError):
            logger.warning("Unexpected timeline structure for @%s", screen_name)
            return tweets

        for instruction in instructions:
            if instruction.get("type") != "TimelineAddEntries":
                continue
            for entry in instruction.get("entries", []):
                tweet = self._parse_entry(entry, screen_name)
                if tweet:
                    tweets.append(tweet)
        return tweets

    def _parse_entry(self, entry: dict, screen_name: str) -> Tweet | None:
        try:
            content = entry["content"]
            if content.get("entryType") != "TimelineTimelineItem":
                return None
            result = content["itemContent"]["tweet_results"]["result"]
            return self._parse_tweet_result(result, screen_name)
        except (KeyError, TypeError):
            return None

    def _parse_tweet_result(self, result: dict, screen_name: str) -> Tweet | None:
        # Handle "TweetWithVisibilityResults" wrapper
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", {})

        if result.get("__typename") not in ("Tweet", None):
            if result.get("__typename") == "TweetTombstone":
                return None

        legacy = result.get("legacy", {})
        if not legacy:
            return None

        tweet_id = legacy.get("id_str") or result.get("rest_id", "")
        text = legacy.get("full_text", "")

        # Check retweet
        is_retweet = False
        rt = legacy.get("retweeted_status_result")
        if rt:
            is_retweet = True
            rt_result = rt.get("result", {})
            rt_legacy = rt_result.get("legacy", {})
            rt_user = rt_result.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
            rt_screen = rt_user.get("screen_name", "unknown")
            text = f"RT @{rt_screen}: {rt_legacy.get('full_text', '')}"

        # Media
        media_urls: list[str] = []
        for media in legacy.get("extended_entities", {}).get("media", []):
            if media.get("type") == "video" or media.get("type") == "animated_gif":
                variants = media.get("video_info", {}).get("variants", [])
                mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4s:
                    best = max(mp4s, key=lambda v: v.get("bitrate", 0))
                    media_urls.append(best["url"])
            else:
                media_urls.append(media.get("media_url_https", ""))

        # Remove t.co URLs from text for cleaner display
        for url_info in legacy.get("entities", {}).get("urls", []):
            expanded = url_info.get("expanded_url", "")
            short = url_info.get("url", "")
            if short and expanded:
                text = text.replace(short, expanded)
        # Remove media t.co links
        for media in legacy.get("entities", {}).get("media", []):
            short = media.get("url", "")
            if short:
                text = text.replace(short, "").strip()

        # Quoted tweet
        quoted_tweet = None
        qt = result.get("quoted_status_result")
        if qt:
            qt_result = qt.get("result", {})
            qt_legacy = qt_result.get("legacy", {})
            qt_user = qt_result.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
            qt_screen = qt_user.get("screen_name", "unknown")
            qt_id = qt_legacy.get("id_str", "")
            quoted_tweet = Tweet(
                id=qt_id,
                text=qt_legacy.get("full_text", ""),
                created_at=qt_legacy.get("created_at", ""),
                url=f"https://x.com/{qt_screen}/status/{qt_id}",
            )

        user_legacy = result.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
        tweet_screen = user_legacy.get("screen_name", screen_name)

        return Tweet(
            id=tweet_id,
            text=text,
            created_at=legacy.get("created_at", ""),
            url=f"https://x.com/{tweet_screen}/status/{tweet_id}",
            media_urls=media_urls,
            is_retweet=is_retweet,
            quoted_tweet=quoted_tweet,
        )
