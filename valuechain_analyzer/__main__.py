"""CLI 엔트리포인트: python -m valuechain_analyzer NVDA"""

import argparse
import asyncio
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        description="ValueChain Analyzer — 밸류체인 분석 및 IR자료 자동 수집",
    )
    parser.add_argument("ticker", help="분석할 미국 주식 티커 (예: NVDA)")
    parser.add_argument(
        "--drive", action="store_true",
        help="Google Drive에 업로드 (credentials.json 필요)",
    )
    parser.add_argument(
        "--filings", type=int, default=2,
        help="filing 유형당 다운로드 수 (기본: 2)",
    )
    parser.add_argument(
        "--quarters", type=int, default=4,
        help="어닝콜 수집 분기 수 (기본: 4)",
    )
    parser.add_argument(
        "--ir-max", type=int, default=20,
        help="IR 프레젠테이션 최대 다운로드 수 (기본: 20)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="상세 로그 출력",
    )
    args = parser.parse_args()

    # 로깅 설정
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from .pipeline import run_pipeline

    print(f"\n{'='*60}")
    print(f"  ValueChain Analyzer — {args.ticker.upper()}")
    print(f"{'='*60}")

    result = asyncio.run(run_pipeline(
        ticker=args.ticker,
        skip_drive=not args.drive,
        num_filings_per_type=args.filings,
        num_transcript_quarters=args.quarters,
        max_ir_count=args.ir_max,
    ))

    # 요약
    print(f"\n{'='*60}")
    print(f"  실행 완료 요약")
    print(f"{'='*60}")
    print(f"  대상 티커: {result.target_ticker}")
    print(f"  밸류체인 기업: {len(result.companies)}개")
    print(f"  SEC filing: {len(result.filings)}개")
    print(f"  어닝콜 트랜스크립트: {len(result.transcripts)}개")
    print(f"  IR 프레젠테이션: {len(result.presentations)}개")
    if result.drive_folder_url:
        print(f"  Drive 폴더: {result.drive_folder_url}")
    print(f"  에러: {len(result.errors)}개")
    print()


if __name__ == "__main__":
    main()
