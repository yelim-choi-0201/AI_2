"""Streamlit deployment recovery edition. Run: streamlit run app.py."""
from __future__ import annotations

from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from importlib.metadata import version, PackageNotFoundError
import hashlib
import json
import math
import sys

import streamlit as st
st.set_page_config(page_title="역별 승하차 | 결과 해석", page_icon="🚉", layout="wide")
try:
    import pandas as pd
    import plotly.graph_objects as go
except ModuleNotFoundError as exc:
    st.title("역별 승하차 이용 분석")
    st.error(f"필수 패키지 설치 누락: {exc.name}")
    st.info("app.py와 같은 폴더에 requirements.txt를 올린 뒤 Reboot app을 실행해 주세요.")
    st.stop()



STATIONS = ["가람역", "누리역", "해솔역", "한빛역"]
REQUIRED = ["일자", "역명", "요일구분", "승차건수", "하차건수", "민원건수"]
SOURCE_SHA256 = "bf9a1ed866500e31c40ad7ca0e7f2456166838b7a25a55ac31fb3bd9b31e8d2a"


CONTENT_SHA256 = '755b883da8aadd2e16800bf7c61b0074745bdd985cc364e9bfa11fb3234aed6e'

def content_fingerprint(df: pd.DataFrame) -> str:
    """Compare parsed values, not BOM, newline style, or row order."""
    canonical = df[REQUIRED].copy()
    canonical[REQUIRED[0]] = canonical[REQUIRED[0]].dt.strftime("%Y-%m-%d")
    canonical = canonical.sort_values(REQUIRED[:2]).reset_index(drop=True)
    payload = json.dumps(canonical.to_dict(orient="records"), ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def find_data_file(base: str | Path) -> Path:
    base = Path(base)
    for relative in ("station_daily_usage.csv", "data/station_daily_usage.csv"):
        candidate = base / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "station_daily_usage.csv가 없습니다. "
        "app.py와 같은 폴더 또는 data/ 폴더에 올려 주세요."
    )


def load_data(path: str | Path, verify_source: bool = False) -> pd.DataFrame:
    """Validate structure and canonical values; do not silently change counts."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {path.name}")
    try:
        try:
            raw = pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            raw = pd.read_csv(path, encoding="cp949")
        frame = validate_data(raw)
    except (ValueError, TypeError, pd.errors.ParserError) as exc:
        raise ValueError(f"CSV 검증 실패: {exc}") from exc
    if verify_source and content_fingerprint(frame) != CONTENT_SHA256:
        raise ValueError(
            "CSV의 실제 데이터가 원본 보고서와 다릅니다. "
            "수정본 ZIP에 들어 있는 CSV로 교체해 주세요. "
            "줄바꿈이나 인코딩 표시 변경은 허용됩니다."
        )
    return frame


def validate_data(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    missing = sorted(set(REQUIRED) - set(df.columns))
    if missing:
        raise ValueError("필수 열이 없습니다: " + ", ".join(missing))
    if df.empty:
        raise ValueError("데이터가 비어 있습니다.")
    if df[REQUIRED].isna().any().any():
        raise ValueError("결측값이 있습니다. 자동 대체하지 않았습니다.")
    df["일자"] = pd.to_datetime(df["일자"], format="%Y-%m-%d", errors="raise")
    if (df["일자"] != df["일자"].dt.normalize()).any():
        raise ValueError("일자 열에는 시간 없이 날짜만 있어야 합니다.")
    if (df["역명"].astype(str).str.strip() == "").any():
        raise ValueError("역명이 비어 있습니다.")
    if df.duplicated(["일자", "역명"]).any():
        raise ValueError("동일 일자·역명 중복이 있습니다. 자동 합산하지 않았습니다.")
    for col in ["승차건수", "하차건수", "민원건수"]:
        values = pd.to_numeric(df[col], errors="raise")
        if (~values.map(math.isfinite)).any() or (values < 0).any():
            raise ValueError(f"{col}에는 유한한 0 이상의 숫자가 필요합니다.")
        if (values % 1 != 0).any():
            raise ValueError(f"{col}에 정수가 아닌 값이 있습니다.")
        df[col] = values.astype("int64")
    expected = df["일자"].dt.dayofweek.map(lambda day: "주말" if day >= 5 else "평일")
    if not df["요일구분"].eq(expected).all():
        raise ValueError("요일구분과 실제 날짜가 일치하지 않습니다.")
    all_dates = pd.date_range(df["일자"].min(), df["일자"].max(), freq="D")
    for station, part in df.groupby("역명", sort=False):
        if len(part) != len(all_dates) or set(part["일자"]) != set(all_dates):
            raise ValueError(f"{station}에 날짜별 기록이 누락되었습니다. 0건으로 채우지 않았습니다.")
    df["승하차합계"] = df["승차건수"] + df["하차건수"]
    return df.sort_values(["일자", "역명"]).reset_index(drop=True)


def select_data(df: pd.DataFrame, stations: list[str], start, end) -> pd.DataFrame:
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    return df.loc[df["역명"].isin(stations) & df["일자"].between(start, end)].copy()


def format_number(value, digits: int = 1, signed: bool = False) -> str:
    """보고서와 동일하게 소수점 반올림(half-up). 부동소수점 끝자리 잡음 제거."""
    if value is None or pd.isna(value):
        return "—"
    number = Decimal(str(round(float(value), 8))).quantize(
        Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
    )
    return format(number, f"{'+' if signed else ''},.{digits}f")


def counts(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"stations": 0, "days": 0, "weekdays": 0, "weekends": 0,
                "rows": 0, "boarding": 0, "alighting": 0, "total": 0, "daily": float("nan")}
    unique_dates = df[["일자", "요일구분"]].drop_duplicates()
    days = len(unique_dates)
    return {
        "stations": df["역명"].nunique(), "days": days, "rows": len(df),
        "weekdays": int(unique_dates["요일구분"].eq("평일").sum()),
        "weekends": int(unique_dates["요일구분"].eq("주말").sum()),
        "boarding": int(df["승차건수"].sum()), "alighting": int(df["하차건수"].sum()),
        "total": int(df["승하차합계"].sum()), "daily": df["승하차합계"].sum() / days,
    }


def summary(df: pd.DataFrame) -> pd.DataFrame:
    result = df.groupby("역명", sort=False).agg(
        승차건수=("승차건수", "sum"), 하차건수=("하차건수", "sum"),
        승하차합계=("승하차합계", "sum"), 관측일수=("일자", "nunique"),
    )
    result["일평균"] = result["승하차합계"] / result["관측일수"]
    result["비중_pct"] = result["승하차합계"] / result["승하차합계"].sum() * 100
    result["승차_하차차이"] = result["승차건수"] - result["하차건수"]
    result["차이비율_pct"] = result["승차_하차차이"] / result["승하차합계"].replace(0, float("nan")) * 100
    ordered = [s for s in STATIONS if s in result.index]
    ordered += [s for s in result.index if s not in ordered]
    return result.reindex(ordered).reset_index()


def daytype_comparison(df: pd.DataFrame, include_total: bool = True) -> pd.DataFrame:
    """합계/관측 일수. 한 요일 유형이 없거나 평일 평균이 0이면 비율은 NaN."""
    rows = []
    names = [s for s in STATIONS if s in set(df["역명"])]
    names += [s for s in df["역명"].unique() if s not in names]
    for name in names + (["선택 역 전체"] if include_total and not df.empty else []):
        part = df if name == "선택 역 전체" else df.loc[df["역명"].eq(name)]
        by_date = part.groupby(["일자", "요일구분"], as_index=False)["승하차합계"].sum()
        weekday = by_date.loc[by_date["요일구분"].eq("평일"), "승하차합계"]
        weekend = by_date.loc[by_date["요일구분"].eq("주말"), "승하차합계"]
        wd, we = weekday.mean(), weekend.mean()
        change = (we / wd - 1) * 100 if pd.notna(wd) and pd.notna(we) and wd != 0 else float("nan")
        rows.append({
            "역명": name, "평일_일수": len(weekday), "주말_일수": len(weekend),
            "평일_일평균": wd, "주말_일평균": we,
            "차이": we - wd, "증감률_pct": change,
        })
    return pd.DataFrame(rows, columns=[
        "역명", "평일_일수", "주말_일수", "평일_일평균", "주말_일평균", "차이", "증감률_pct"
    ])


def extrema(df: pd.DataFrame) -> dict:
    """동률 최대·최소일을 모두 보존."""
    if df.empty:
        raise ValueError("최대·최소를 계산할 데이터가 없습니다.")
    high, low = int(df["승하차합계"].max()), int(df["승하차합계"].min())
    return {
        "max": high, "min": low,
        "max_dates": df.loc[df["승하차합계"].eq(high), "일자"].dt.strftime("%m/%d").tolist(),
        "min_dates": df.loc[df["승하차합계"].eq(low), "일자"].dt.strftime("%m/%d").tolist(),
    }


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Excel에서 한글을 읽을 수 있도록 UTF-8 BOM을 포함."""
    out = df.copy()
    for col in out.select_dtypes(include=["datetime"]).columns:
        out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode("utf-8-sig")

fmt = format_number

def polish(fig: go.Figure, height: int = 400) -> go.Figure:
    fig.update_layout(
        height=height,
        font=dict(family="Arial, 'Noto Sans CJK KR', 'Malgun Gothic', sans-serif", size=13),
        margin=dict(l=24, r=28, t=44, b=45),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
        hoverlabel=dict(namelength=-1),
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def daily_chart(part: pd.DataFrame, mode: str = "승차·하차", y_max: float | None = None) -> go.Figure:
    part = part.sort_values("일자")
    fig = go.Figure()
    items = [("승차건수", "승차", "solid", "circle"), ("하차건수", "하차", "dash", "square")]
    if mode == "승하차 합계":
        items = [("승하차합계", "승하차 합계", "solid", "circle")]
    for column, label, dash, symbol in items:
        fig.add_trace(go.Scatter(
            x=part["일자"], y=part[column], name=label, mode="lines+markers",
            line=dict(width=2.5, dash=dash), marker=dict(size=7, symbol=symbol),
            customdata=part[["요일구분"]],
            hovertemplate=label + " %{y:,}건 (%{customdata[0]})<extra></extra>",
        ))
    for day in part.loc[part["요일구분"].eq("주말"), "일자"].unique():
        day = pd.Timestamp(day)
        fig.add_vrect(
            x0=day - pd.Timedelta(hours=12), x1=day + pd.Timedelta(hours=12),
            fillcolor=fig.layout.template.layout.font.color,
            opacity=0.10, line_width=0, layer="below",
        )
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(
        title="일자", tickformat="%m/%d", dtick=86400000,
        range=[part["일자"].min() - pd.Timedelta(hours=12),
               part["일자"].max() + pd.Timedelta(hours=12)],
    )
    fig.update_yaxes(title="승하차 건수 (건)", rangemode="tozero")
    if y_max is not None:
        fig.update_yaxes(range=[0, y_max])
    return polish(fig, 420)


def comparison_chart(table: pd.DataFrame) -> go.Figure:
    table = table.loc[table["역명"] != "선택 역 전체"]
    fig = go.Figure()
    for column, label in [("평일_일평균", "평일"), ("주말_일평균", "주말")]:
        fig.add_trace(go.Bar(
            x=table["역명"], y=table[column], name=label,
            text=table[column].map(lambda x: format_number(x, 1)),
            textposition="outside", cliponaxis=False,
            customdata=table[column].map(lambda x: format_number(x, 1)),
            hovertemplate="%{x}<br>" + label + " %{customdata}건/일<extra></extra>",
        ))
    fig.update_layout(barmode="group", hovermode="x unified")
    fig.update_yaxes(title="일평균 승하차 합계 (건/일)", rangemode="tozero")
    fig.update_xaxes(title=None)
    return polish(fig, 410)


def ranking_chart(table: pd.DataFrame) -> go.Figure:
    table = table.sort_values("승하차합계", ascending=True)
    fig = go.Figure(go.Bar(
        y=table["역명"], x=table["승하차합계"], orientation="h",
        text=table["승하차합계"].map(lambda n: f"{n:,}건"), textposition="outside",
        cliponaxis=False, hovertemplate="%{y}<br>승하차 합계 %{x:,}건<extra></extra>",
    ))
    fig.update_xaxes(title="기간 승하차 합계 (건)", range=[0, table["승하차합계"].max() * 1.26])
    fig.update_yaxes(title=None)
    return polish(fig, 310)

REPORT_TITLE = "역별 승하차 이용 분석"
REPORT_FILENAME = "역별_승하차_결과해석_보고서_가독성개선.docx"
REPORT_PERIOD = "2026.09.07 - 2026.09.20"
REPORT_DATE = "2026.10.21"

HEADLINE = "전체 이용량의 변화는 작지만, 평일과 주말에 이용이 집중되는 역은 뚜렷하게 달라진다."
STATION_TEXT = {
    "가람역": {
        "title": "가장 큰 누적 규모, 뚜렷한 주말 감소",
        "observed": "주말 일평균은 평일보다 556.6건 적으며, 승차가 하차보다 많은 상태가 14일 모두 이어졌다.",
        "meaning": "주말 감소 후 다음 평일에 다시 높아지는 흐름을 보이므로 단순한 지속 감소로 해석하기 어렵다. 출퇴근 목적 때문인지는 일별 자료만으로 확인할 수 없다.",
    },
    "누리역": {
        "title": "평일 우세, 가람역보다 완만한 주말 감소",
        "observed": "누적 합계는 16,643건으로 4개 역 중 2위다.",
        "meaning": "가람역과 같은 방향의 요일 차이를 보이지만 감소폭은 더 작다. 승차와 하차의 일별 움직임은 대체로 유사하며, 9월 13일에는 전날보다 이용량이 늘어 주말 내부에도 차이가 있음을 보여 준다.",
    },
    "해솔역": {
        "title": "주말에 거의 두 배로 커지는 이용 규모",
        "observed": "주말 일평균은 평일의 약 1.97배다. 주말 일별 합계 1,603~1,695건은 평일 범위 724~958건을 모두 웃돈다.",
        "meaning": "4개 역 중 요일에 따른 이용 규모 차이가 가장 크며, 주말 4일 모두 일별 합계 1위였다. 주말 운영 상태를 우선 관찰할 근거는 되지만, 관광·쇼핑 등 특정 이용 목적이나 실제 혼잡 발생을 입증하지는 않는다.",
    },
    "한빛역": {
        "title": "주말 평균 증가, 날짜별 변동도 함께 확인",
        "observed": "누적 합계는 10,218건으로 가장 적지만, 주말 일평균은 평일보다 24.5% 높다. 기간 합계로는 하차가 승차보다 198건 많다.",
        "meaning": "주말 증가 경향이 해솔역만큼 일관되게 분리되지는 않는다. 평일인 9월 9일의 851건은 첫 주말의 802건·761건보다 많다. 평균 차이를 모든 주말이 모든 평일보다 많다는 뜻으로 확대해서는 안 된다.",
    },
}
COMPARISON_TEXT = [
    (
        "평일 1위와 주말 1위가 다르다",
        "가람역은 평일 일평균 1,739.8건으로 1위지만, 주말에는 해솔역이 1,650.3건으로 1위가 된다. 해솔역은 누적 이용량에서는 3위다.",
    ),
    (
        "반대 방향의 변화가 상쇄된다",
        "가람·누리 -808.6건/일 + 해솔·한빛 +981.2건/일 = 전체 +172.6건/일. 이는 역별 건수의 구성 변화이며, 같은 이용자가 다른 역으로 이동했다는 뜻은 아니다.",
    ),
    (
        "두 주의 방향은 같지만 장기 특성은 아니다",
        "각 주의 평일·주말 평균을 따로 비교해도 네 역의 증감 방향은 두 주 모두 동일하다. 다만 관측된 주말은 두 차례이므로 장기적인 요일 특성으로 확정하기에는 이르다.",
    ),
]
OPERATIONS = [
    {
        "관찰 대상": "가람역·누리역 / 평일",
        "확인할 내용": "시간대별 승하차와 현장 대기 상황",
        "판단 범위": "일별 합계만으로 인력 증원 확정 불가",
    },
    {
        "관찰 대상": "해솔역 / 주말",
        "확인할 내용": "안내·개찰구·승강장의 현장 상태 우선 확인",
        "판단 범위": "이용 증가를 실제 혼잡으로 단정하지 않음",
    },
    {
        "관찰 대상": "한빛역 / 주말",
        "확인할 내용": "평균 증가와 개별 날짜의 편차",
        "판단 범위": "모든 주말이 평일보다 많다고 해석하지 않음",
    },
]
LIMITATIONS = [
    ("건수 ≠ 고유 이용자 수", "승하차 합계는 중복을 제거한 실제 이용자 수가 아니다. 동일인의 반복 이용이나 승차·하차를 함께 포함할 수 있다."),
    ("14일의 기술통계", "주말 관측은 4일뿐이다. 장기 추세, 계절성, 이용 목적, 날씨나 행사 등 변화 원인을 이 자료만으로 확정할 수 없다."),
    ("이용 규모 ≠ 혼잡·안전 위험", "하루 건수만으로 시간대 혼잡도, 열차·시설 수용능력, 안전 위험을 판단할 수 없다. 날짜별 최대값도 별도 판정 기준 없이 이상 현상이라고 단정하지 않았다."),
    ("승차·하차 차이 ≠ 순유입 인구", "승차·하차 차이는 이용 기록의 차이일 뿐 순유입 인구나 거주·체류 인구를 뜻하지 않는다. 출발지·도착지 연결 자료가 없어 네 역 사이의 이동 관계도 알 수 없다."),
]
CONCLUSION = "관측 기간에는 가람·누리역의 평일 우세와 해솔·한빛역의 주말 우세가 함께 나타났다. 특히 해솔역의 주말 증가가 가장 뚜렷하며, 전체 합계보다 역별·요일별 차이를 함께 보는 해석이 중요하다."

ROOT = Path(__file__).resolve().parent
st.markdown("""
<style>
.block-container {max-width:1450px; padding-top:2.2rem; padding-bottom:3rem;}
h1,h2,h3 {letter-spacing:-0.04em; word-break:keep-all;}
[data-testid="stMetricValue"] {letter-spacing:-0.04em;}
.hero-label {font-size:0.75rem; font-weight:700; letter-spacing:0.15em;
             color:#0F766E; margin-bottom:0.55rem;}
.scope-note {border-left:4px solid #0F766E; padding:0.75rem 1rem;
             background:#F3F6FA; border-radius:0 8px 8px 0; margin:0.8rem 0 1.2rem;}
@media (max-width:700px) {
 .block-container {padding-left:1rem; padding-right:1rem;}
 h1 {font-size:1.8rem;}
}
</style>
""", unsafe_allow_html=True)


st.markdown('<div class="hero-label">STATION INSIGHT · 결과 해석 대시보드</div>', unsafe_allow_html=True)
st.title(REPORT_TITLE)
st.caption(f"보고서 작성일 {REPORT_DATE} · 원본 분석 기간 {REPORT_PERIOD}")

with st.expander("배포 점검: 파일·설치 버전", expanded=False):
    st.caption("복구본 v2 | Python " + sys.version.split()[0])
    package_versions = {}
    for package in ("streamlit", "pandas", "plotly"):
        try:
            package_versions[package] = version(package)
        except PackageNotFoundError:
            package_versions[package] = "미설치"
    st.json(package_versions)
    st.write({
        "station_daily_usage.csv": (ROOT / "station_daily_usage.csv").is_file(),
        "data/station_daily_usage.csv": (ROOT / "data/station_daily_usage.csv").is_file(),
        "requirements.txt": (ROOT / "requirements.txt").is_file(),
    })
    st.caption("false는 해당 경로에 파일이 없다는 뜻입니다. CSV 경로 두 개 중 하나는 true여야 합니다.")

def read_source() -> pd.DataFrame:
    # 56 rows: reading per rerun is inexpensive and avoids stale cached files.
    return load_data(find_data_file(ROOT), verify_source=True)


def show_frame(frame: pd.DataFrame, formatters: dict | None = None):
    styled = frame.style.format(formatters or {}, na_rep="—")
    st.dataframe(styled, hide_index=True, width="stretch")


def show_figure(fig, key: str):
    st.plotly_chart(
        fig, width="stretch", key=key,
        config={"displaylogo": False, "scrollZoom": False,
                "toImageButtonOptions": {"format": "png", "scale": 2}},
    )


def reset_filters():
    st.session_state["station_filter"] = STATIONS.copy()
    st.session_state["period_filter"] = (raw["일자"].min().date(), raw["일자"].max().date())


try:
    raw = read_source()
except (OSError, ValueError, TypeError, pd.errors.ParserError) as exc:
    st.error(f"데이터를 불러오지 못했습니다. {exc}")
    st.info("화면 상단의 '배포 점검'을 펼치면 파일 누락을 확인할 수 있습니다.")
    st.stop()

available = [name for name in STATIONS if name in set(raw["역명"])]
min_day, max_day = raw["일자"].min().date(), raw["일자"].max().date()

with st.sidebar:
    st.markdown("### 조회 조건")
    st.caption("기본값은 원본 보고서의 전체 분석 범위입니다.")
    selected = st.multiselect("역 선택", available, default=available, key="station_filter")
    period = st.date_input(
        "조회 기간", value=(min_day, max_day), min_value=min_day, max_value=max_day,
        format="YYYY/MM/DD", key="period_filter",
    )
    st.button("전체 기간·역으로 초기화", on_click=reset_filters, width="stretch")
    fixed_scale = st.toggle("역별 그래프 세로축 통일", value=True, key="fixed_scale")
    st.caption("승차·하차 그래프를 역 간 같은 척도로 비교합니다.")
    st.divider()
    st.markdown("**데이터 안내**")
    st.caption("원본: station_daily_usage.csv\n\n단위: 승차·하차 건수\n\n민원건수는 승하차 분석에 포함하지 않습니다.")
    st.caption("‘종합 해석’과 원본 보고서는 전체 14일 기준으로 고정됩니다.")


if not selected:
    st.info("왼쪽에서 한 개 이상의 역을 선택해 주세요.")
    st.stop()
if not isinstance(period, (tuple, list)) or len(period) != 2:
    st.info("조회 기간의 시작일과 종료일을 모두 선택해 주세요.")
    st.stop()

try:
    filtered = select_data(raw, selected, period[0], period[1])
except ValueError as exc:
    st.warning(str(exc))
    st.stop()
if filtered.empty:
    st.warning("선택한 조건에 해당하는 기록이 없습니다.")
    st.stop()

n = counts(filtered)
stats = summary(filtered)
comparison = daytype_comparison(filtered)
all_row = comparison.loc[comparison["역명"].eq("선택 역 전체")].iloc[0]
full_scope = set(selected) == set(available) and tuple(period) == (min_day, max_day)
st.markdown(
    f'<div class="scope-note"><b>현재 집계</b> &nbsp; {period[0]:%Y.%m.%d} - {period[1]:%Y.%m.%d}'
    f' &nbsp; | &nbsp; {n["stations"]}개 역 · {n["days"]}일'
    f' &nbsp; | &nbsp; 평일 {n["weekdays"]}일 / 주말 {n["weekends"]}일</div>',
    unsafe_allow_html=True,
)
if not full_scope:
    st.caption("필터 적용 중: 수치·표·그래프는 선택 범위로 재계산됩니다. 원본 보고서의 고정 해석은 별도 표시합니다.")

kpis = st.columns(4)
kpis[0].metric("승하차 합계", f'{n["total"]:,}건', border=True)
kpis[1].metric("승차", f'{n["boarding"]:,}건', border=True)
kpis[2].metric("하차", f'{n["alighting"]:,}건', border=True)
kpis[3].metric("선택 역 전체 일평균", f'{fmt(n["daily"])}건/일', border=True)
st.caption("승하차 합계는 고유 이용자 수가 아닙니다. 같은 사람의 반복 이용과 승차·하차가 포함될 수 있습니다.")

overview, weekday_tab, detail, interpretation, data_tab = st.tabs(
    ["한눈에 보기", "평일·주말 비교", "역별 추이", "종합 해석", "데이터·보고서"]
)

with overview:
    st.subheader("평일과 주말, 역마다 방향이 다릅니다." if full_scope else "선택 범위의 역별 요일 차이")
    if full_scope:
        st.write(HEADLINE)
    cols = st.columns(len(stats))
    for col, station in zip(cols, stats["역명"]):
        row = comparison.loc[comparison["역명"].eq(station)].iloc[0]
        rate = row["증감률_pct"]
        with col, st.container(border=True):
            st.caption(station)
            st.metric("평일 대비 주말", f"{fmt(rate, signed=True)}%" if pd.notna(rate) else "비교 불가")
            if pd.isna(rate):
                st.caption("평일·주말을 모두 포함하고 평일 평균이 0보다 커야 합니다.")
            else:
                direction = "증가" if rate > 0 else "감소" if rate < 0 else "동일"
                st.caption(f"주말 {direction} · 일평균 기준")
            st.caption(f'평일 {fmt(row["평일_일평균"])} → 주말 {fmt(row["주말_일평균"])}건/일')
    if pd.notna(all_row["증감률_pct"]):
        st.info(f'선택 역 전체의 주말 일평균은 평일 대비 {fmt(all_row["증감률_pct"], signed=True)}%입니다. '
                "역별 반대 방향의 변화를 전체 합계만으로 판단하지 마세요.")
    else:
        st.info("선택 범위에는 비교 가능한 평일·주말 쌍이 없어 증감률을 계산하지 않았습니다.")
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        st.markdown("#### 기간 이용 규모")
        show_figure(ranking_chart(stats), "ranking")
    with right:
        st.markdown("#### 역별 집계")
        table = stats[["역명", "승차건수", "하차건수", "승하차합계", "일평균", "비중_pct"]].rename(
            columns={"승차건수": "승차 (건)", "하차건수": "하차 (건)", "승하차합계": "합계 (건)",
                     "일평균": "일평균 (건/일)", "비중_pct": "비중 (%)"})
        show_frame(table, {
            "승차 (건)": lambda x: fmt(x, 0), "하차 (건)": lambda x: fmt(x, 0),
            "합계 (건)": lambda x: fmt(x, 0), "일평균 (건/일)": fmt, "비중 (%)": fmt,
        })
        st.caption("비중의 분모는 현재 선택한 역·기간의 승하차 합계입니다.")

with weekday_tab:
    st.subheader("관측 일수가 다르므로 일평균으로 비교합니다.")
    st.caption("주말은 토·일요일입니다. 증감률 = (주말 일평균 ÷ 평일 일평균 - 1) × 100")
    if n["weekdays"] == 0 or n["weekends"] == 0:
        st.warning("평일 또는 주말 기록이 없는 기간입니다. 없는 유형의 평균과 증감률은 ‘—’로 표시합니다.")
    show_figure(comparison_chart(comparison), "daytype")
    ctable = comparison.rename(columns={
        "평일_일수": "평일 (일)", "주말_일수": "주말 (일)",
        "평일_일평균": "평일 평균 (건/일)", "주말_일평균": "주말 평균 (건/일)",
        "차이": "차이 (건/일)", "증감률_pct": "주말 증감률 (%)",
    })
    show_frame(ctable, {
        "평일 평균 (건/일)": fmt, "주말 평균 (건/일)": fmt,
        "차이 (건/일)": lambda x: fmt(x, signed=True),
        "주말 증감률 (%)": lambda x: fmt(x, signed=True),
    })
    st.caption("차이와 증감률은 반올림 전 평균에서 계산합니다. 마지막 행은 선택 역의 일별 합계를 기준으로 계산합니다.")
    with st.expander("원본 보고서의 비교 해석 | 전체 4개 역·14일 기준", expanded=full_scope):
        for heading, body in COMPARISON_TEXT:
            st.markdown(f"**{heading}**")
            st.write(body)

with detail:
    st.subheader("날짜별 흐름과 최대·최소일")
    select_col, mode_col = st.columns([1, 1.5])
    with select_col:
        station = st.selectbox("상세 분석 역", stats["역명"].tolist(), key="detail_station")
    with mode_col:
        mode = st.radio("표시 지표", ["승차·하차", "승하차 합계"], horizontal=True, key="chart_mode")
    part = filtered.loc[filtered["역명"].eq(station)].copy()
    ext = extrema(part)
    row = comparison.loc[comparison["역명"].eq(station)].iloc[0]
    detail_cols = st.columns(3)
    detail_cols[0].metric("평일 대비 주말 일평균", f'{fmt(row["증감률_pct"], signed=True)}%' if pd.notna(row["증감률_pct"]) else "비교 불가", border=True)
    detail_cols[1].metric("최대 일별 합계", f'{ext["max"]:,}건', border=True)
    detail_cols[1].caption("해당 날짜 " + ", ".join(ext["max_dates"]))
    detail_cols[2].metric("최소 일별 합계", f'{ext["min"]:,}건', border=True)
    detail_cols[2].caption("해당 날짜 " + ", ".join(ext["min_dates"]))
    ymax = None
    if fixed_scale:
        source_max = raw[["승차건수", "하차건수"]].to_numpy().max() if mode == "승차·하차" else raw["승하차합계"].max()
        ymax = math.ceil(float(source_max) * 1.10 / 100) * 100
    show_figure(daily_chart(part, mode, ymax), "daily_station")
    st.caption("음영은 주말입니다. 승차는 실선·원, 하차는 점선·사각형입니다. 최대·최소는 승차와 하차를 더한 일별 합계입니다.")
    if fixed_scale:
        st.caption(f"세로축: 0~{ymax:,}건. 모든 역에 같은 원본 전체 범위를 적용합니다.")
    with st.expander(f"원본 보고서의 {station} 해석 | {REPORT_PERIOD}", expanded=True):
        st.caption("아래 설명은 원본 전체 기간의 해석이며, 현재 필터 범위의 해석이 아닙니다.")
        narrative = STATION_TEXT[station]
        st.markdown(f'**{narrative["title"]}**')
        st.markdown("**관찰 결과**")
        st.write(narrative["observed"])
        st.markdown("**해석**")
        st.write(narrative["meaning"])
    with st.expander("선택 역의 일별 숫자 보기"):
        show_frame(part[["일자", "요일구분", "승차건수", "하차건수", "승하차합계"]].assign(
            일자=part["일자"].dt.strftime("%Y-%m-%d")))

with interpretation:
    st.subheader("종합 판단과 결과의 활용 범위")
    st.info(f"이 탭은 원본 보고서의 전체 4개 역·14일({REPORT_PERIOD}) 기준입니다. 왼쪽 필터와 무관하게 고정됩니다.")
    st.markdown("#### 승차와 하차의 차이")
    original_stats = summary(raw)
    imbalance = original_stats[["역명", "승차_하차차이", "차이비율_pct"]].rename(
        columns={"승차_하차차이": "승차 - 하차 (건)", "차이비율_pct": "차이 ÷ 승하차 합계 (%)"})
    show_frame(imbalance, {
        "승차 - 하차 (건)": lambda x: fmt(x, 0, signed=True),
        "차이 ÷ 승하차 합계 (%)": lambda x: fmt(x, signed=True),
    })
    st.caption("양수는 승차 우세, 음수는 하차 우세입니다. 이용 기록 차이이지 순유입 인구가 아닙니다.")
    st.markdown("#### 데이터에 근거한 운영 검토 방향")
    st.table(pd.DataFrame(OPERATIONS))
    st.write("모든 역에 동일한 운영 기준을 적용하기보다 역별·요일별 관측 결과를 구분해 검토할 필요가 있습니다. "
             "이는 운영 변경의 확정안이 아니라 추가 확인의 우선순위입니다.")
    st.markdown("#### 결과 해석 시 주의사항")
    for heading, body in LIMITATIONS:
        with st.expander(heading, expanded=True):
            st.write(body)
    st.markdown("#### 결론")
    st.write(CONCLUSION)
    st.caption(f"해석 출처: {REPORT_FILENAME}의 02~05절. 원문의 관찰·해석·한계를 유지했습니다.")

with data_tab:
    st.subheader("데이터 확인과 보고서 내려받기")
    st.markdown("#### 원본 데이터 품질")
    audit = st.columns(4)
    audit[0].metric("결측값", int(raw.isna().sum().sum()), border=True)
    audit[1].metric("일자·역명 중복", int(raw.duplicated(["일자", "역명"]).sum()), border=True)
    audit[2].metric("음수 건수 값", int((raw[["승차건수", "하차건수", "민원건수"]] < 0).sum().sum()), border=True)
    audit[3].metric("날짜·요일 일치", "전체 일치", border=True)
    st.caption("원본 56행·6열. 삭제·대체·보간 없이 사용하며, 파일 형식이 아닌 실제 값으로 원본 일치 여부를 확인합니다.")
    st.markdown("#### 현재 선택 범위의 데이터")
    visible = filtered[["일자", "역명", "요일구분", "승차건수", "하차건수", "승하차합계", "민원건수"]].copy()
    visible["일자"] = visible["일자"].dt.strftime("%Y-%m-%d")
    st.dataframe(visible, hide_index=True, width="stretch")
    st.caption("민원건수는 원본 확인을 위해 표시하며, 위의 승하차 지표·해석에는 사용하지 않습니다.")
    d1, d2, d3 = st.columns(3)
    d1.download_button("선택 데이터 CSV", csv_bytes(filtered), "station_filtered.csv", "text/csv", width="stretch")
    d2.download_button("역별 집계 CSV", csv_bytes(stats), "station_summary.csv", "text/csv", width="stretch")
    d3.download_button("평일·주말 비교 CSV", csv_bytes(comparison), "station_daytype_comparison.csv", "text/csv", width="stretch")
    st.markdown("#### 원본 보고서")
    report = next((p for p in (ROOT / "station_report.docx", ROOT / "assets/station_report.docx") if p.is_file()), ROOT / "station_report.docx")
    if report.is_file():
        st.download_button(
            "가독성 개선 보고서 받기 · Word", report.read_bytes(), REPORT_FILENAME,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
        )
    else:
        st.info("station_report.docx가 없어 Word 다운로드만 비활성화됩니다. 다른 분석 기능은 사용할 수 있습니다.")
    st.caption("Word 파일은 전체 14일 기준의 기존 보고서입니다. 필터 조건에 맞춰 새로 생성되는 보고서가 아닙니다.")
    with st.expander("집계 기준과 재현 정보"):
        st.markdown("""
승하차 합계는 **승차건수 + 하차건수**입니다. 일평균은 해당 범위의 합계를 실제 관측 일수로 나눕니다.
원본 전체 기간은 14일(평일 10일, 주말 4일)입니다.

주말 증감률은 **(주말 일평균 ÷ 평일 일평균 - 1) × 100**입니다.
비교할 요일 유형이 없거나 평일 평균이 0인 경우 증감률을 계산하지 않습니다.

소수점 첫째 자리 표시는 반올림하며, 증감률과 차이는 반올림 전 값으로 계산합니다.
비중은 현재 선택한 역·기간의 승하차 합계를 분모로 사용합니다.

원본 데이터: `station_daily_usage.csv`  
원본 보고서: `station_report.docx`  
자동으로 갱신되는 실시간 데이터가 아니라 고정된 분석 자료입니다.
""")

st.divider()
st.caption("자료: station_daily_usage.csv · 해석: 역별_승하차_결과해석_보고서_가독성개선.docx · 단위: 건")
