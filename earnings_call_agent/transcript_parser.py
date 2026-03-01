"""트랜스크립트 역할 분류 (operator / executive / analyst)

dcf.py 출력 [{speaker_name, content}] →
qa_organizer.py 입력 [{role, speaker_name, speaker_firm, content}] 변환

3단계:
1. Q&A 경계 탐지 (operator/진행자 발언 중 전환 문구)
2. Speaker 분류 (operator / executive / analyst)
3. 블록 어노테이션
"""

import logging
import re

logger = logging.getLogger(__name__)

_OPERATOR_NAMES = {"operator", "conference operator", "conference call operator"}

# 우선순위 높은 전환 문구 (analyst Q&A 전용)
_ANALYST_QA_PHRASES = [
    "analyst questions",
    "move on to analyst",
    "move to analyst",
    "questions from analyst",
]

# 일반 Q&A 전환 문구
_QA_TRANSITION_PHRASES = [
    "question-and-answer",
    "question and answer",
    "q&a session",
    "q&a portion",
    "open the floor for questions",
    "open the call to questions",
    "open it up for questions",
    "take your first question",
    "first question comes from",
    "first question, please",
    "may we have the first question",
    "open the line",
    "begin the question",
    "questions and answers",
    "limit yourself to two questions",
    "limit yourself to one question",
]

# "Joseph Moore - Morgan Stanley" 패턴
_ANALYST_PATTERN = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")

# 진행자 소개에서 firm 추출
_FIRM_PATTERNS = [
    # "from Name of Firm" / "from Name with Firm"
    re.compile(r"from\s+(.+?)\s+(?:of|with)\s+([A-Z][\w &'\-]+)", re.IGNORECASE),
    # "from Name at Firm" (Tesla 등)
    re.compile(r"from\s+(.+?)\s+at\s+([A-Z][\w &'\-]+)", re.IGNORECASE),
    # "from Name from Firm" (Tesla: "from Andrew from Morgan Stanley")
    re.compile(r"from\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+from\s+([A-Z][\w &'\-]+)"),
    # "is Name from Firm" (Tesla: "first analyst is Emmanuel from Wolfe")
    re.compile(r"is\s+(.+?)\s+from\s+([A-Z][\w &'\-]+)", re.IGNORECASE),
    # "Name calling from Firm"
    re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+calling from\s+([A-Z][\w &'\-]+)"),
]


def classify_and_split(
    raw_blocks: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Raw blocks를 역할 분류하고 prepared_remarks / qa_blocks로 분리."""
    if not raw_blocks:
        return [], []

    # Step 1: Q&A 경계 탐지
    qa_start_idx = _find_qa_boundary(raw_blocks)

    # Step 2: Prepared remarks에서 executive 이름 수집
    exec_names: set[str] = set()
    for block in raw_blocks[:qa_start_idx]:
        name = block.get("speaker_name", "").strip()
        if name and not _is_operator(name):
            exec_names.add(name.lower())

    # Step 3: 진행자/Operator 소개 블록에서 analyst→firm 매핑 추출
    analyst_firms = _extract_analyst_firms(raw_blocks[qa_start_idx:], exec_names)

    # Step 4: 블록 어노테이션 및 분리
    prepared_remarks = []
    qa_blocks = []

    for i, block in enumerate(raw_blocks):
        annotated = _annotate_block(block, exec_names)

        # Q&A 섹션에서 unknown → analyst 승격 + firm 부여
        if i >= qa_start_idx and annotated["role"] == "unknown":
            annotated["role"] = "analyst"
            name_lower = annotated["speaker_name"].lower()
            firm = analyst_firms.get(name_lower)
            # 풀네임 매칭 실패 시 first name으로 재시도
            if not firm:
                first = name_lower.split()[0] if name_lower else ""
                firm = analyst_firms.get(first)
            if firm:
                annotated["speaker_firm"] = firm

        if i < qa_start_idx:
            prepared_remarks.append(annotated)
        else:
            qa_blocks.append(annotated)

    logger.info(
        f"분류 완료: prepared_remarks={len(prepared_remarks)}, "
        f"qa_blocks={len(qa_blocks)}, executives={exec_names}"
    )
    return prepared_remarks, qa_blocks


def _find_qa_boundary(blocks: list[dict]) -> int:
    """Q&A 섹션 시작 인덱스를 찾는다.

    탐색 우선순위:
    0. Analyst Q&A 전용 문구 (모든 블록, 500자 이하) — TSLA 등
    1. Operator 블록에서 일반 전환 문구
    2. 짧은 블록(진행자/호스트)에서 일반 전환 문구
    """
    # 0차: Analyst Q&A 전용 문구 (가장 높은 우선순위)
    for i, block in enumerate(blocks):
        if i < 3:
            continue
        content = block.get("content", "").strip()
        if len(content) > 500:
            continue
        content_lower = content.lower()
        for phrase in _ANALYST_QA_PHRASES:
            if phrase in content_lower:
                name = block.get("speaker_name", "").strip()
                logger.debug(f"Q&A 경계(analyst QA): block {i}, [{name}], phrase='{phrase}'")
                return i

    # 1차: Operator 블록에서 일반 전환 문구
    for i, block in enumerate(blocks):
        if i < 3:
            continue
        name = block.get("speaker_name", "").strip()
        if not _is_operator(name):
            continue
        content = block.get("content", "").strip().lower()
        for phrase in _QA_TRANSITION_PHRASES:
            if phrase in content:
                logger.debug(f"Q&A 경계(operator): block {i}, [{name}], phrase='{phrase}'")
                return i

    # 2차: 짧은 블록(진행자/호스트)에서 일반 전환 문구 — 500자 이하
    for i, block in enumerate(blocks):
        if i < 3:
            continue
        content = block.get("content", "").strip()
        if len(content) > 500:
            continue
        content_lower = content.lower()
        for phrase in _QA_TRANSITION_PHRASES:
            if phrase in content_lower:
                name = block.get("speaker_name", "").strip()
                logger.debug(f"Q&A 경계(host): block {i}, [{name}], phrase='{phrase}'")
                return i

    logger.warning("Q&A 경계를 찾지 못함 — 전체를 prepared remarks로 처리")
    return len(blocks)


def _extract_analyst_firms(qa_blocks: list[dict], exec_names: set[str]) -> dict[str, str]:
    """진행자/Operator 소개 블록에서 analyst 이름→firm 매핑 추출.

    exec_names에 있는 사람이 소개하는 블록도 탐색한다.
    (Tesla의 Travis Axelrod 등 IR 담당자)
    """
    mapping: dict[str, str] = {}
    for block in qa_blocks:
        name = block.get("speaker_name", "").strip()
        # Operator 또는 executive(IR 진행자)의 소개 블록
        is_moderator = _is_operator(name) or name.lower() in exec_names
        if not is_moderator:
            continue
        content = block.get("content", "")
        for pat in _FIRM_PATTERNS:
            match = pat.search(content)
            if match:
                analyst_name = match.group(1).strip().rstrip(".")
                firm = match.group(2).strip().rstrip(".")
                # exec 본인은 제외
                if analyst_name.lower() not in exec_names:
                    mapping[analyst_name.lower()] = firm
                    logger.debug(f"Analyst firm 추출: {analyst_name} → {firm}")
                break
    return mapping


def _is_operator(name: str) -> bool:
    """Operator 여부 판별."""
    return name.strip().lower() in _OPERATOR_NAMES


def _annotate_block(block: dict, exec_names: set[str]) -> dict:
    """블록에 role, speaker_firm 추가."""
    name = block.get("speaker_name", "").strip()
    content = block.get("content", "").strip()

    result = {
        "speaker_name": name,
        "content": content,
        "speaker_firm": "",
        "role": "unknown",
    }

    # Operator 판별
    if _is_operator(name):
        result["role"] = "operator"
        return result

    # Analyst 패턴: "Name - Firm"
    match = _ANALYST_PATTERN.match(name)
    if match:
        analyst_name = match.group(1).strip()
        firm = match.group(2).strip()
        if analyst_name.lower() not in exec_names:
            result["role"] = "analyst"
            result["speaker_name"] = analyst_name
            result["speaker_firm"] = firm
            return result

    # 알려진 executive
    if name.lower() in exec_names:
        result["role"] = "executive"
        return result

    return result
