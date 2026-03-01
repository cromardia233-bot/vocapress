"""Q&A 섹션을 증권사/애널리스트별로 구조화"""

import logging

logger = logging.getLogger(__name__)


def organize_qa(qa_blocks: list[dict]) -> list[dict]:
    """Q&A 블록을 질문-답변 쌍으로 구조화.

    입력: transcript_parser에서 파싱된 qa 블록 리스트
    출력: [
        {
            "analyst_name": "Joseph Moore",
            "analyst_firm": "Morgan Stanley",
            "question": "Can you discuss...",
            "answer": "(Jensen Huang) Blackwell demand...",
            "answerer_name": "Jensen Huang",
        },
        ...
    ]
    """
    pairs = []
    current_q = None
    current_answers = []

    for block in qa_blocks:
        role = block.get("role", "unknown")
        name = block.get("speaker_name", "")
        firm = block.get("speaker_firm", "")
        content = block.get("content", "").strip()

        if not content:
            continue

        if role == "operator":
            # Operator 발언은 Q&A 경계로 사용
            if current_q and current_answers:
                pairs.append(_make_pair(current_q, current_answers))
            current_q = None
            current_answers = []
            continue

        if role == "analyst":
            # 이전 질문이 있었으면 마감
            if current_q is not None and current_answers:
                pairs.append(_make_pair(current_q, current_answers))

            # 새 질문 시작
            current_q = {
                "analyst_name": name,
                "analyst_firm": firm,
                "question": content,
            }
            current_answers = []

        elif role == "executive" or role == "unknown":
            if current_q:
                current_answers.append({
                    "name": name,
                    "content": content,
                })
            # Q 없이 executive가 말하면 무시 (예: 추가 발언)

    # 마지막 쌍
    if current_q and current_answers:
        pairs.append(_make_pair(current_q, current_answers))

    # 실질적 질문이 없는 쌍 필터 (인사/감사 등)
    pairs = [p for p in pairs if _has_substance(p)]
    logger.info(f"Q&A 구조화 완료: {len(pairs)} 쌍")
    return pairs


def _has_substance(pair: dict) -> bool:
    """Q&A 쌍에 실질적 내용이 있는지 판별."""
    q = pair.get("question", "").strip()
    a = pair.get("answer", "").strip()
    if not q and not a:
        return False
    # 답변이 짧으면 인사/소개/잡담 (실질적 답변은 200자+)
    if len(a) < 200:
        return False
    return True


def _make_pair(question_info: dict, answers: list[dict]) -> dict:
    """Q&A 쌍 딕셔너리 생성."""
    # 답변 합치기
    answer_parts = []
    primary_answerer = answers[0]["name"] if answers else ""

    for ans in answers:
        prefix = f"({ans['name']}) "
        answer_parts.append(prefix + ans["content"])

    return {
        "analyst_name": question_info["analyst_name"],
        "analyst_firm": question_info.get("analyst_firm", ""),
        "question": question_info["question"],
        "answer": "\n\n".join(answer_parts),
        "answerer_name": primary_answerer,
    }
