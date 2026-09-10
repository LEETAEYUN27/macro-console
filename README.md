# 글로벌 경제 관제실 (macro-console)

지수·원자재·환율·미국/한국 섹터·기관 13F·부동산·경제 안정성·FOMC 경로를 한 화면에 모은 거시 관제 페이지.
**GitHub Actions 가 매일 1회 자동으로 데이터를 새로 수집하여 GitHub Pages 에 재배포한다.** Claude 세션이나 수동 조작이 필요 없다.

- 데이터 갱신 : 매일 22:00 UTC = **07:00 KST** (미국 정규장 마감 이후)
- 비용 : 0원 (Public 저장소 + GitHub Actions 무료 한도 + API 키 불필요 공개 데이터만 사용)
- 소요 : 1회 실행 약 5~10분

---

## 1. 최초 설치 (1회, 약 10분)

### 1-1. 저장소 생성

1. GitHub → **New repository**
2. Repository name : `macro-console`
3. **Public** 선택 ← Private 은 GitHub Pages 무료 발행이 불가
4. Create repository

> 이 저장소에는 공개 거시 지표만 들어간다. 보유 종목·평단·손절선 등 개인 포지션 정보는 일절 포함되지 않으므로 Public 으로 두어도 노출 위험이 없다.

### 1-2. 파일 업로드

1. 생성된 저장소 첫 화면 → **uploading an existing file** 클릭
2. 압축을 푼 `macro-console` 폴더 **안의 내용물 전체**를 드래그하여 업로드
   - 폴더째가 아니라 **안의 파일·폴더들**을 올릴 것
   - `.github` 폴더가 누락되면 자동 실행이 되지 않으므로 반드시 포함할 것
3. Commit changes

> **⚠ `.github` 폴더 주의 (Windows)**
> 점(`.`)으로 시작하는 폴더는 탐색기에서 기본적으로 숨겨져 있어 드래그 시 누락되기 쉽다.
> 압축 해제 후 탐색기 상단 **보기 → 표시 → 숨긴 항목**을 켜고 `.github`·`.gitignore` 가 보이는지 확인한 뒤 업로드할 것.
> 그래도 올라가지 않으면 저장소에서 **Add file → Create new file** 을 누르고,
> 파일명 칸에 `.github/workflows/build.yml` 을 그대로 입력한 뒤 (슬래시를 치면 폴더가 자동 생성된다)
> 압축 파일 안의 `build.yml` 내용을 붙여넣고 Commit 하면 된다. `.gitignore` 도 같은 방법으로 만든다.

업로드 후 저장소 구조는 다음과 같아야 한다.

```
.github/workflows/build.yml
config/universe.json
config/narrative.json
config/institutions.json
docs/manifest.webmanifest
docs/sw.js
docs/icon-192.png
docs/icon-512.png
docs/icon-512-maskable.png
docs/.nojekyll
build_console.py
shell.html
requirements.txt
.gitignore
README.md
```

### 1-3. GitHub Pages 설정

1. 저장소 → **Settings** → 좌측 **Pages**
2. **Source** 를 `Deploy from a branch` 가 아니라 **`GitHub Actions`** 로 변경
3. 저장

### 1-4. 첫 실행

1. 저장소 → **Actions** 탭 → 좌측 **「관제실 일일 갱신」**
2. 우측 **Run workflow** → 초록 버튼 클릭
3. 5~10분 대기 (build → deploy 두 단계가 모두 초록색이 되면 완료)
4. Settings → Pages 상단에 표시되는 주소가 관제실 URL 이다

```
https://<GitHub 아이디>.github.io/macro-console/
```

이후로는 매일 07:00 KST 에 자동으로 갱신된다.

---

## 2. 휴대폰 홈화면에 설치

기존 claude.ai 아티팩트 바로가기는 **삭제**하고 새 주소로 다시 설치할 것.

- **안드로이드 (Chrome)** : 새 주소 접속 → 우상단 ⋮ → `홈 화면에 추가` / `앱 설치`
- **아이폰 (Safari)** : 새 주소 접속 → 공유 버튼 → `홈 화면에 추가`

앱 이름은 「경제 관제실」, 아이콘은 게이지 형태로 표시되며 주소창 없는 전체화면으로 열린다.
접속할 때마다 최신 데이터를 먼저 내려받고, 통신이 끊긴 경우에만 마지막으로 본 화면을 보여준다.

---

## 3. 화면 구성

| 탭 | 내용 |
|---|---|
| 시장 | 주가지수 11 · 원자재 8 · 환율/금리 8 — 타일 클릭 시 1년(일봉)·5년·전체(월봉) 차트 |
| 섹터 | 미국 SPDR 11 · 한국 ETF 8 — 1개월/3개월/YTD/1년 히트맵 전환 |
| 기관 보유 | 버크셔·블랙록·국민연금·뱅가드 상위 10 종목 (SEC 13F 원문 파싱) |
| 이벤트·시나리오 | FOMC 금리 반영 확률 · 시나리오별 파급 경로 · 주요 경제 일정 |
| 경제 안정성 | 7개 축 종합 점수 + 핵심 지표 + 뉴욕연준 12개월 침체확률 추이 |
| 부동산·리츠 | 미국/한국 리츠 9 · 미국 주택가격 지수 2 |

---

## 4. 경제 안정성 점수 산식

7개 축을 각각 0~100점(100 = 가장 안정)으로 환산하여 **단순 평균**한다.

| 축 | 지표 | 100점 | 0점 |
|---|---|---|---|
| 침체 확률 | 뉴욕연준 수익률곡선 모형 12개월 | 0% | 60% |
| 물가 | 근원 CPI 전년비의 2% 목표 이격 | 0.0%p | 5.0%p |
| 금융여건 | 시카고연준 NFCI | −0.5 | +1.5 |
| 수익률곡선 | 10년 − 3개월 (채권등가) | +1.5%p | −0.6%p |
| 시장 스트레스 | VIX | 12 | 48 |
| 고용 | 실업률 | 3.5% | 10.0% |
| 시장 밸류에이션 | 실러 CAPE | 10 | 42 |

- 구간 밖의 값은 0점 또는 100점으로 절사한다.
- **점수 자체보다 어느 축이 무너지고 있는지가 판단 재료다.** 현재는 CAPE 축만 홀로 0점대에 있고 경기 지표 6개는 70점 이상이다.
- 구간을 바꾸려면 `build_console.py` 의 `build_stability()` 안 `band(...)` 인자를 수정한다.

### ⚠ 거시 센티널 메일의 MRS 와 방향이 반대다

| 구분 | 지표 | 스케일 |
|---|---|---|
| 거시 센티널 메일 (invest-tower) | MRS 거시**위험**점수 | **0 = 안전**, 100 = 위험 |
| 이 관제실 | 경제 **안정성** | 0 = 위험, **100 = 안정** |

두 숫자를 같은 축으로 비교하지 말 것.

---

## 5. 데이터 출처 (전부 무료·API 키 불필요)

| 항목 | 출처 |
|---|---|
| 시세 55종 | Yahoo Finance (yfinance) |
| 금리·물가·고용·금융여건 | FRED CSV 직접 다운로드 (DFF·DGS10·DGS3MO·T10Y3M·CPILFESL·UNRATE·NFCI·MORTGAGE30US) |
| 침체 확률 | 뉴욕연준 `allmonth.xls` |
| 실러 CAPE | multpl.com |
| 미국 주택가격 | Zillow ZHVI · FRED 케이스-실러 |
| 기관 보유 | SEC EDGAR 13F-HR 원문 |

---

## 6. 설정 변경 (GitHub 웹에서 직접 수정)

| 파일 | 수정 대상 |
|---|---|
| `config/universe.json` | 화면에 띄울 종목·지수 추가/삭제 (`name`, `ticker`) |
| `config/narrative.json` | 경제 일정(`events`), 시나리오(`scenarios`), 면책 문구 |
| `config/institutions.json` | 추적할 기관과 SEC CIK |
| `.github/workflows/build.yml` | 실행 시각 (`cron`) |

파일을 수정하고 Commit 하면 다음 자동 실행부터 반영된다. 즉시 반영하려면 Actions 탭에서 **Run workflow** 를 누른다.

> 참고 — 저장소에 이미 등록된 기관 CIK
> 버크셔 `0001067983` · 블랙록 `0002012383` · 국민연금 `0001608046` · 뱅가드 `0000102909`
> (블랙록은 2024년 지주사 개편으로 CIK 가 바뀌었다. 구 CIK `0001364742` 는 2024년 2분기에서 신고가 멈춰 있으므로 사용하지 말 것.)

---

## 7. 장애 시 동작

| 상황 | 동작 |
|---|---|
| 개별 종목 시세 실패 | 해당 타일만 제외하고 나머지는 정상 생성 |
| 시세 전량 실패 | 직전 배포본의 시세를 그대로 유지하고 거시 지표만 갱신 |
| 연방기금 선물 수집 실패 | 3개월 국채금리 기준 대체 환산으로 전환하고 화면에 ⚠ 표기 |
| CAPE·침체확률 등 개별 거시 실패 | 해당 축을 평균에서 제외하고 나머지 축으로 점수 산출 |
| 전체 실패 | Actions 가 빨간색으로 표시되고 **직전 배포본이 그대로 유지**된다 (빈 화면이 되지 않음) |

실행 기록은 Actions 탭에서, 상세 로그는 배포된 페이지의 `/build.log` 에서 확인한다.

---

## 8. 로컬에서 직접 실행

```bash
pip install -r requirements.txt
python build_console.py
# docs/index.html 생성 → 브라우저로 열기
```
