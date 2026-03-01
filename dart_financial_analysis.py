"""
한국 반도체 기업 재무지표 비교 분석 스크립트
- 20개 기업의 10년(2015~2024) 재무데이터에서 주요 항목 추출
- 6개 재무비율 산출 및 기업 간 비교
"""

import re
import pandas as pd
import numpy as np
from pathlib import Path

# 파일 경로
INPUT_FILE = Path(__file__).parent / "한국_반도체_재무제표_10년.xlsx"
OUTPUT_FILE = Path(__file__).parent / "한국_반도체_재무분석_비교.xlsx"

# 제외할 시트
EXCLUDE_SHEETS = {"실패내역", "요약"}

# 재무항목별 매칭 설정: (재무제표구분 리스트, 계정명 후보 리스트)
# 계정명은 우선순위 순서 (정확히 일치하는 것 사용)
ITEM_CONFIG = {
    "매출액": {
        "statements": ["손익계산서", "포괄손익계산서"],
        "accounts": ["매출액", "수익(매출액)", "매출", "수익", "매출액 및 지분법손익"],
    },
    "영업이익": {
        "statements": ["손익계산서", "포괄손익계산서"],
        "accounts": ["영업이익", "영업이익(손실)", "영업순손익", "영업손익"],
    },
    "당기순이익": {
        "statements": ["손익계산서", "포괄손익계산서"],
        "accounts": ["당기순이익", "당기순이익(손실)", "당기순손익"],
    },
    "자산총계": {
        "statements": ["재무상태표"],
        "accounts": ["자산총계"],
    },
    "부채총계": {
        "statements": ["재무상태표"],
        "accounts": ["부채총계"],
    },
    "자본총계": {
        "statements": ["재무상태표"],
        "accounts": ["자본총계"],
    },
    "영업활동현금흐름": {
        "statements": ["현금흐름표"],
        "accounts": [
            "영업활동현금흐름",
            "영업활동 현금흐름",
            "영업활동으로인한현금흐름",
            "영업활동으로 인한 현금흐름",
            "영업활동으로 창출된 현금흐름",
        ],
    },
}


def stripPrefix(name):
    """로마숫자·번호 접두사 제거 (예: 'Ⅰ. 매출액' → '매출액', 'I. 영업활동...' → '영업활동...')"""
    s = str(name)
    # 유니코드 로마숫자 (Ⅰ~Ⅹ), 영문 로마숫자 (I, II, III, IV, V, VI, VII, VIII, IX, X)
    s = re.sub(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*', '', s)
    s = re.sub(r'^[IVXivx]+\.\s*', '', s)
    # 번호 접두사: (1), (2) 등
    s = re.sub(r'^\(\d+\)\s*', '', s)
    return s.strip()


def extractFinancialItem(df, year, statements, accounts):
    """특정 연도·재무제표에서 계정명 매칭하여 당기금액 추출"""
    # 해당 연도·재무제표구분 필터
    mask = (df["사업연도"] == year) & (df["재무제표구분"].isin(statements))
    subset = df[mask]

    # 1차: 우선순위 순서대로 정확 매칭 시도
    for account in accounts:
        matched = subset[subset["계정명"] == account]
        if len(matched) > 0:
            return matched["당기금액"].iloc[0]

    # 2차: 로마숫자/번호 접두사 제거 후 매칭
    for account in accounts:
        matched = subset[subset["계정명"].apply(stripPrefix) == account]
        if len(matched) > 0:
            return matched["당기금액"].iloc[0]

    # 3차: 공백 모두 제거 후 매칭 (예: "자 산 총 계" → "자산총계")
    for account in accounts:
        matched = subset[subset["계정명"].str.replace(" ", "", regex=False) == account]
        if len(matched) > 0:
            return matched["당기금액"].iloc[0]

    return np.nan


def extractCompanyData(df, company):
    """한 기업의 전체 연도 재무항목 추출"""
    years = sorted(df["사업연도"].unique())
    records = []

    for year in years:
        row = {"기업": company, "연도": int(year)}
        for item_name, config in ITEM_CONFIG.items():
            val = extractFinancialItem(
                df, year, config["statements"], config["accounts"]
            )
            row[item_name] = val

        # 매출액 폴백: 매출원가 + 매출총이익 (매출액 항목 자체가 누락된 경우)
        if pd.isna(row["매출액"]):
            stmts = ["손익계산서", "포괄손익계산서"]
            costAccounts = ["매출원가"]
            grossAccounts = ["매출총이익", "매출총이익(손실)"]
            cost = extractFinancialItem(df, year, stmts, costAccounts)
            gross = extractFinancialItem(df, year, stmts, grossAccounts)
            if not pd.isna(cost) and not pd.isna(gross):
                row["매출액"] = cost + gross

        # 자본총계 폴백: 자산총계 - 부채총계
        if pd.isna(row["자본총계"]) and not pd.isna(row["자산총계"]) and not pd.isna(row["부채총계"]):
            row["자본총계"] = row["자산총계"] - row["부채총계"]

        records.append(row)

    return records


def calculateRatios(df):
    """재무비율 산출"""
    result = df.copy()

    # 영업이익률(%)
    result["영업이익률(%)"] = np.where(
        result["매출액"] != 0,
        result["영업이익"] / result["매출액"] * 100,
        np.nan,
    )

    # 순이익률(%)
    result["순이익률(%)"] = np.where(
        result["매출액"] != 0,
        result["당기순이익"] / result["매출액"] * 100,
        np.nan,
    )

    # ROE(%)
    result["ROE(%)"] = np.where(
        result["자본총계"] != 0,
        result["당기순이익"] / result["자본총계"] * 100,
        np.nan,
    )

    # ROA(%)
    result["ROA(%)"] = np.where(
        result["자산총계"] != 0,
        result["당기순이익"] / result["자산총계"] * 100,
        np.nan,
    )

    # 부채비율(%)
    result["부채비율(%)"] = np.where(
        result["자본총계"] != 0,
        result["부채총계"] / result["자본총계"] * 100,
        np.nan,
    )

    # 영업CF/매출(%)
    result["영업CF/매출(%)"] = np.where(
        result["매출액"] != 0,
        result["영업활동현금흐름"] / result["매출액"] * 100,
        np.nan,
    )

    return result


def buildPivotSheet(data, items, unit_억=True):
    """기업×연도 피벗 테이블 생성 (억원 단위 변환 옵션)"""
    sheets = {}
    for item in items:
        pivot = data.pivot_table(
            index="기업", columns="연도", values=item, aggfunc="first"
        )
        if unit_억:
            pivot = (pivot / 1e8).round(1)  # 억원 단위, 소수점 1자리
        else:
            pivot = pivot.round(2)  # 비율은 소수점 2자리
        sheets[item] = pivot
    return sheets


def buildRankingSheet(data, years=range(2022, 2025)):
    """최근 3년 평균 기준 종합 순위표"""
    recent = data[data["연도"].isin(years)]

    # 기업별 평균
    avg = recent.groupby("기업").agg({
        "매출액": "mean",
        "영업이익": "mean",
        "당기순이익": "mean",
        "영업이익률(%)": "mean",
        "순이익률(%)": "mean",
        "ROE(%)": "mean",
        "ROA(%)": "mean",
        "부채비율(%)": "mean",
        "영업CF/매출(%)": "mean",
    })

    # 억원 단위 변환 (금액 항목만)
    for col in ["매출액", "영업이익", "당기순이익"]:
        avg[col] = (avg[col] / 1e8).round(1)

    # 비율 소수점 2자리
    ratio_cols = ["영업이익률(%)", "순이익률(%)", "ROE(%)", "ROA(%)", "부채비율(%)", "영업CF/매출(%)"]
    for col in ratio_cols:
        avg[col] = avg[col].round(2)

    # 영업이익 기준 내림차순 정렬
    avg = avg.sort_values("영업이익", ascending=False)
    avg.insert(0, "순위", range(1, len(avg) + 1))

    return avg


def main():
    print("=== 한국 반도체 기업 재무분석 시작 ===\n")

    # 시트명 확인
    xl = pd.ExcelFile(INPUT_FILE)
    companies = [s for s in xl.sheet_names if s not in EXCLUDE_SHEETS]
    print(f"분석 대상: {len(companies)}개 기업")

    # Step 1: 재무항목 추출
    print("\n[Step 1] 재무항목 추출 중...")
    allRecords = []
    for company in companies:
        df = pd.read_excel(INPUT_FILE, sheet_name=company)
        records = extractCompanyData(df, company)
        allRecords.extend(records)
        yearCount = len(records)
        print(f"  {company}: {yearCount}개 연도")

    data = pd.DataFrame(allRecords)
    print(f"\n총 {len(data)}건 추출 완료")

    # Step 2: 재무비율 계산
    print("\n[Step 2] 재무비율 산출 중...")
    data = calculateRatios(data)
    print("  6개 비율 산출 완료")

    # Step 3: 엑셀 파일 생성
    print("\n[Step 3] 엑셀 파일 생성 중...")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        # 시트 1: 재무항목_원본 (억원 단위)
        items = ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계", "영업활동현금흐름"]
        pivots = buildPivotSheet(data, items, unit_억=True)

        # 모든 항목을 하나의 시트에 결합
        rawParts = []
        for item_name, pivot in pivots.items():
            # 항목명 라벨 행 추가
            header = pd.DataFrame(
                [[f"▶ {item_name} (억원)"] + [""] * (len(pivot.columns) - 1)],
                columns=pivot.columns,
                index=[""],
            )
            rawParts.append(header)
            rawParts.append(pivot)
            # 빈 행 추가
            blank = pd.DataFrame(
                [[""] * len(pivot.columns)],
                columns=pivot.columns,
                index=[""],
            )
            rawParts.append(blank)

        rawSheet = pd.concat(rawParts)
        rawSheet.to_excel(writer, sheet_name="재무항목_원본")
        print(f"  재무항목_원본: {len(rawSheet)}행")

        # 시트 2: 수익성_비교
        profitRatios = buildPivotSheet(data, ["영업이익률(%)", "순이익률(%)"], unit_억=False)
        profitParts = []
        for rname, pivot in profitRatios.items():
            header = pd.DataFrame(
                [[f"▶ {rname}"] + [""] * (len(pivot.columns) - 1)],
                columns=pivot.columns,
                index=[""],
            )
            profitParts.append(header)
            profitParts.append(pivot)
            blank = pd.DataFrame(
                [[""] * len(pivot.columns)],
                columns=pivot.columns,
                index=[""],
            )
            profitParts.append(blank)

        profitSheet = pd.concat(profitParts)
        profitSheet.to_excel(writer, sheet_name="수익성_비교")
        print(f"  수익성_비교: {len(profitSheet)}행")

        # 시트 3: 효율성_비교
        effRatios = buildPivotSheet(data, ["ROE(%)", "ROA(%)"], unit_억=False)
        effParts = []
        for rname, pivot in effRatios.items():
            header = pd.DataFrame(
                [[f"▶ {rname}"] + [""] * (len(pivot.columns) - 1)],
                columns=pivot.columns,
                index=[""],
            )
            effParts.append(header)
            effParts.append(pivot)
            blank = pd.DataFrame(
                [[""] * len(pivot.columns)],
                columns=pivot.columns,
                index=[""],
            )
            effParts.append(blank)

        effSheet = pd.concat(effParts)
        effSheet.to_excel(writer, sheet_name="효율성_비교")
        print(f"  효율성_비교: {len(effSheet)}행")

        # 시트 4: 안정성_비교
        safeRatios = buildPivotSheet(data, ["부채비율(%)"], unit_억=False)
        safeParts = []
        for rname, pivot in safeRatios.items():
            header = pd.DataFrame(
                [[f"▶ {rname}"] + [""] * (len(pivot.columns) - 1)],
                columns=pivot.columns,
                index=[""],
            )
            safeParts.append(header)
            safeParts.append(pivot)

        safeSheet = pd.concat(safeParts)
        safeSheet.to_excel(writer, sheet_name="안정성_비교")
        print(f"  안정성_비교: {len(safeSheet)}행")

        # 시트 5: 종합_순위
        ranking = buildRankingSheet(data)
        ranking.to_excel(writer, sheet_name="종합_순위")
        print(f"  종합_순위: {len(ranking)}행")

    print(f"\n출력 파일: {OUTPUT_FILE}")

    # Step 4: 검증
    print("\n[Step 4] 검증...")

    # 삼성전자 2024 영업이익
    samsung2024 = data[(data["기업"] == "삼성전자") & (data["연도"] == 2024)]
    if len(samsung2024) > 0:
        opIncome = samsung2024["영업이익"].iloc[0]
        print(f"  삼성전자 2024 영업이익: {opIncome/1e12:.1f}조원 (기대값: ~32.7조)")

    # SK하이닉스 2024 영업이익
    sk2024 = data[(data["기업"] == "SK하이닉스") & (data["연도"] == 2024)]
    if len(sk2024) > 0:
        opIncome = sk2024["영업이익"].iloc[0]
        print(f"  SK하이닉스 2024 영업이익: {opIncome/1e12:.1f}조원 (기대값: ~23.5조)")

    print("\n=== 분석 완료 ===")


if __name__ == "__main__":
    main()
