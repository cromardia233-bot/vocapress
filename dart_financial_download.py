"""
DART OpenAPI를 이용한 한국 반도체 기업 10년치 재무제표 다운로드
- 대상: 반도체 관련 기업 20개
- 기간: 2015~2024 (사업보고서 기준)
- 출력: 엑셀 파일 (기업별 시트)
"""

import requests
import pandas as pd
import zipfile
import io
import xml.etree.ElementTree as ET
import time
import sys

# === 설정 ===
API_KEY = "99c555bd78d21da658dd02e5a86cbef78cdc113b"
YEARS = list(range(2015, 2025))  # 2015~2024
REPRT_CODE = "11011"  # 사업보고서(연간)
OUTPUT_FILE = "/Users/suhunchoi/Desktop/Claude code/한국_반도체_재무제표_10년.xlsx"

# 대상 기업 리스트 (검색용 이름 → 시트명)
TARGET_COMPANIES = {
    "삼성전자": "삼성전자",
    "에스케이하이닉스": "SK하이닉스",
    "한미반도체": "한미반도체",
    "원익IPS": "원익IPS",
    "주성엔지니어링": "주성엔지니어링",
    "피에스케이": "PSK",
    "이오테크닉스": "이오테크닉스",
    "티이에스": "TES",
    "유진테크": "유진테크",
    "에이치피에스피": "HPSP",
    "솔브레인홀딩스": "솔브레인홀딩스",
    "동진쎄미켐": "동진쎄미켐",
    "티씨케이": "TCK",
    "후성": "후성",
    "디엔에프": "DNF",
    "디비하이텍": "DB하이텍",
    "리노공업": "리노공업",
    "네패스": "네패스",
    "하나마이크론": "하나마이크론",
    "파크시스템스": "파크시스템스",
}

# DART에서 기업명이 다를 수 있으므로 대체 검색명도 준비
ALTERNATIVE_NAMES = {
    "에스케이하이닉스": ["SK하이닉스", "에스케이하이닉스"],
    "원익IPS": ["원익아이피에스", "원익IPS"],
    "티이에스": ["테스", "티이에스", "TES"],
    "에이치피에스피": ["HPSP", "에이치피에스피"],
    "솔브레인홀딩스": ["솔브레인홀딩스", "솔브레인"],
    "디비하이텍": ["DB하이텍", "디비하이텍"],
    "피에스케이": ["피에스케이", "PSK"],
    "티씨케이": ["티씨케이", "TCK"],
    "디엔에프": ["디엔에프", "DNF"],
}


def download_corp_codes():
    """DART에서 전체 기업 고유번호 ZIP 다운로드 후 XML 파싱"""
    print("=" * 60)
    print("[Step 1] 기업 고유번호(corp_code) 다운로드 중...")
    print("=" * 60)

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": API_KEY}

    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        print(f"  [오류] HTTP {resp.status_code}")
        sys.exit(1)

    # ZIP 파일 해제 후 XML 파싱
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_filename = zf.namelist()[0]
        with zf.open(xml_filename) as f:
            tree = ET.parse(f)

    root = tree.getroot()
    corp_list = []
    for item in root.findall("list"):
        corp_list.append({
            "corp_code": item.findtext("corp_code"),
            "corp_name": item.findtext("corp_name"),
            "stock_code": item.findtext("stock_code"),
        })

    print(f"  전체 기업 수: {len(corp_list):,}개")
    return corp_list


def find_corp_codes(corp_list):
    """대상 기업의 corp_code 매핑"""
    # 상장기업만 필터 (stock_code가 있는 것)
    listed = {c["corp_name"]: c["corp_code"] for c in corp_list if c["stock_code"] and c["stock_code"].strip()}

    matched = {}
    not_found = []

    for search_name, display_name in TARGET_COMPANIES.items():
        # 1차: 정확히 일치
        if search_name in listed:
            matched[search_name] = {"corp_code": listed[search_name], "display_name": display_name}
            print(f"  [매칭] {display_name} → {listed[search_name]} (정확 매칭: {search_name})")
            continue

        # 2차: 대체 이름으로 검색
        found = False
        alt_names = ALTERNATIVE_NAMES.get(search_name, [])
        for alt in alt_names:
            if alt in listed:
                matched[search_name] = {"corp_code": listed[alt], "display_name": display_name}
                print(f"  [매칭] {display_name} → {listed[alt]} (대체명: {alt})")
                found = True
                break

        if not found:
            # 3차: 부분 매칭 (기업명에 포함된 경우)
            candidates = []
            search_terms = [search_name] + alt_names
            for term in search_terms:
                for name, code in listed.items():
                    if term in name or name in term:
                        candidates.append((name, code))

            if len(candidates) == 1:
                matched[search_name] = {"corp_code": candidates[0][1], "display_name": display_name}
                print(f"  [매칭] {display_name} → {candidates[0][1]} (부분매칭: {candidates[0][0]})")
            elif len(candidates) > 1:
                # 가장 짧은 이름 선택 (보통 정확한 기업명)
                best = min(candidates, key=lambda x: len(x[0]))
                matched[search_name] = {"corp_code": best[1], "display_name": display_name}
                print(f"  [매칭] {display_name} → {best[1]} (후보 중 선택: {best[0]})")
            else:
                not_found.append(display_name)
                print(f"  [실패] {display_name} - corp_code를 찾을 수 없음")

    print(f"\n  매칭 성공: {len(matched)}개 / 실패: {len(not_found)}개")
    if not_found:
        print(f"  미매칭 기업: {', '.join(not_found)}")

    return matched


def fetch_financial_data(corp_code, year, fs_div="CFS"):
    """단일 기업/연도의 재무제표 API 호출"""
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": API_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": REPRT_CODE,
        "fs_div": fs_div,
    }

    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"

    data = resp.json()
    status = data.get("status")
    message = data.get("message", "")

    if status == "000":  # 정상
        return data.get("list", []), None
    elif status == "013":  # 조회된 데이터가 없음
        return None, "데이터 없음"
    else:
        return None, f"[{status}] {message}"


def download_all_financials(matched_companies):
    """모든 기업의 10년치 재무제표 다운로드"""
    print("\n" + "=" * 60)
    print("[Step 2] 재무제표 다운로드 중...")
    print(f"  대상: {len(matched_companies)}개 기업 × {len(YEARS)}년 = {len(matched_companies) * len(YEARS)}건")
    print("=" * 60)

    all_data = {}  # {display_name: [records...]}
    failures = []  # (display_name, year, reason)
    total_calls = 0
    success_count = 0

    for search_name, info in matched_companies.items():
        corp_code = info["corp_code"]
        display_name = info["display_name"]
        all_data[display_name] = []

        print(f"\n  [{display_name}]")

        for year in YEARS:
            total_calls += 1

            # CFS(연결재무제표) 먼저 시도
            records, error = fetch_financial_data(corp_code, year, "CFS")

            if records is None:
                # CFS 실패 시 OFS(개별재무제표)로 fallback
                time.sleep(1)
                records, error = fetch_financial_data(corp_code, year, "OFS")
                if records:
                    # OFS로 가져온 경우 표시
                    for r in records:
                        r["fs_div"] = "OFS"
                    print(f"    {year}: OFS {len(records)}건 (CFS 없음)")
                    success_count += 1
                else:
                    failures.append((display_name, year, error or "CFS/OFS 모두 없음"))
                    print(f"    {year}: 실패 - {error}")
            else:
                print(f"    {year}: CFS {len(records)}건")
                success_count += 1

            if records:
                # 연도 정보 추가
                for r in records:
                    r["bsns_year"] = str(year)
                all_data[display_name].extend(records)

            time.sleep(1)  # API 호출 제한 (초당 1회)

    print(f"\n  총 API 호출: {total_calls}건")
    print(f"  성공: {success_count}건 / 실패: {len(failures)}건")

    return all_data, failures


def create_excel(all_data, failures):
    """엑셀 파일 생성 (기업별 시트)"""
    print("\n" + "=" * 60)
    print("[Step 3] 엑셀 파일 생성 중...")
    print("=" * 60)

    # 주요 컬럼 정의 및 한글 변환
    columns_order = [
        "bsns_year", "sj_nm", "account_nm",
        "thstrm_nm", "thstrm_amount",
        "frmtrm_nm", "frmtrm_amount",
        "bfefrmtrm_nm", "bfefrmtrm_amount",
        "ord", "fs_div", "fs_nm", "currency",
    ]
    column_labels = {
        "bsns_year": "사업연도",
        "sj_nm": "재무제표구분",
        "account_nm": "계정명",
        "thstrm_nm": "당기명",
        "thstrm_amount": "당기금액",
        "frmtrm_nm": "전기명",
        "frmtrm_amount": "전기금액",
        "bfefrmtrm_nm": "전전기명",
        "bfefrmtrm_amount": "전전기금액",
        "ord": "정렬순서",
        "fs_div": "재무제표유형",
        "fs_nm": "재무제표유형명",
        "currency": "통화",
    }

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        sheet_count = 0

        for display_name, records in all_data.items():
            if not records:
                print(f"  [{display_name}] 데이터 없음 - 시트 생략")
                continue

            df = pd.DataFrame(records)

            # 존재하는 컬럼만 선택
            available_cols = [c for c in columns_order if c in df.columns]
            df = df[available_cols]

            # 컬럼명 한글로 변환
            df = df.rename(columns={c: column_labels.get(c, c) for c in df.columns})

            # 금액 컬럼 숫자 변환
            for col in ["당기금액", "전기금액", "전전기금액"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

            # 정렬: 사업연도(내림차순) → 재무제표구분 → 정렬순서
            sort_cols = []
            if "사업연도" in df.columns:
                sort_cols.append("사업연도")
            if "재무제표구분" in df.columns:
                sort_cols.append("재무제표구분")
            if "정렬순서" in df.columns:
                df["정렬순서"] = pd.to_numeric(df["정렬순서"], errors="coerce")
                sort_cols.append("정렬순서")
            if sort_cols:
                ascending = [False] + [True] * (len(sort_cols) - 1)
                df = df.sort_values(sort_cols, ascending=ascending)

            # 시트명 (엑셀 시트명 31자 제한, 특수문자 제거)
            sheet_name = display_name[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            sheet_count += 1
            print(f"  [{display_name}] {len(df)}행 저장")

        # 실패 내역 시트 추가
        if failures:
            fail_df = pd.DataFrame(failures, columns=["기업명", "사업연도", "사유"])
            fail_df.to_excel(writer, sheet_name="실패내역", index=False)
            print(f"  [실패내역] {len(failures)}건")

        # 요약 시트 추가
        summary_rows = []
        for display_name, records in all_data.items():
            if records:
                years_available = sorted(set(r.get("bsns_year", "") for r in records))
                summary_rows.append({
                    "기업명": display_name,
                    "데이터건수": len(records),
                    "가용연도": ", ".join(years_available),
                    "연도수": len(years_available),
                })
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            summary_df.to_excel(writer, sheet_name="요약", index=False)

    print(f"\n  엑셀 파일 저장 완료: {OUTPUT_FILE}")
    print(f"  총 시트 수: {sheet_count}개 (+ 요약/실패내역)")


def main():
    print("DART OpenAPI - 한국 반도체 기업 재무제표 다운로드")
    print(f"대상 기간: {YEARS[0]}~{YEARS[-1]} ({len(YEARS)}년)")
    print(f"대상 기업: {len(TARGET_COMPANIES)}개\n")

    # Step 1: 기업 고유번호 매핑
    corp_list = download_corp_codes()
    matched = find_corp_codes(corp_list)

    if not matched:
        print("\n[오류] 매칭된 기업이 없습니다. 종료합니다.")
        sys.exit(1)

    # Step 2: 재무제표 다운로드
    all_data, failures = download_all_financials(matched)

    # Step 3: 엑셀 파일 생성
    create_excel(all_data, failures)

    # 최종 결과 요약
    print("\n" + "=" * 60)
    print("[완료] 최종 결과")
    print("=" * 60)
    total_records = sum(len(v) for v in all_data.values())
    companies_with_data = sum(1 for v in all_data.values() if v)
    print(f"  데이터 보유 기업: {companies_with_data}/{len(matched)}개")
    print(f"  총 레코드 수: {total_records:,}건")
    print(f"  실패 건수: {len(failures)}건")
    print(f"  출력 파일: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
