# us-close-briefing

미국 주식 마감 후 시장 흐름을 자동 요약해 Telegram으로 전송하는 Python 기반 브리핑 자동화 프로젝트입니다.

주요 지수, 시가총액 상위 종목, 섹터 ETF, 뉴스 데이터를 수집한 뒤, OpenAI를 통해 짧고 읽기 쉬운 Telegram용 마감 브리핑을 생성합니다.

---

## Features

- 미국 주요 지수 자동 수집
  - S&P 500
  - Nasdaq
  - Dow
  - Russell 2000
  - VIX

- 시가총액 상위 종목 자동 수집
  - NVIDIA
  - Microsoft
  - Apple
  - Amazon
  - Alphabet
  - Meta
  - Tesla
  - Broadcom
  - Berkshire Hathaway
  - JPMorgan

- 섹터/산업 강약 자동 수집
  - Technology
  - Communication Services
  - Consumer Discretionary
  - Financials
  - Industrials
  - Energy
  - Health Care
  - Consumer Staples
  - Utilities
  - Real Estate
  - Materials
  - Semiconductors
  - Software
  - Biotech / Banks / Regional Banks
  - Cybersecurity / Cloud Computing / AI & Robotics
  - Clean Energy / Homebuilders / Aerospace & Defense
  - U.S. Infrastructure / Oil & Gas Exploration / Gold Miners

- 뉴스 자동 수집
  - Alpha Vantage `NEWS_SENTIMENT`
  - CNBC RSS => 수집 안됨
  - Investing.com RSS
  - 뉴스 품질 필터(광고/영상성 콘텐츠, 짧은 제목, 중복 제목/링크 제거)

- 보강 데이터 수집
  - Alpha Vantage `TOP_GAINERS_LOSERS`

- AI 브리핑 자동 생성
  - 한 줄 총평
  - 지수 흐름
  - 자금 흐름
  - 핵심 종목
  - 강한 곳 / 약한 곳
  - 체크포인트
  - 참고 링크

- Telegram 자동 발송
- 미국 휴장일 자동 인식(휴장일/주말 자동 skip)
- 테스트 모드 요일 체크 우회(`TEST_MODE=true`)
- 커스텀 종목 브리핑(`CUSTOM_WATCHLIST`)
- HTML 메시지 스타일 개선(섹션 아이콘, 가독성 향상)
- 재시도 및 fallback 메시지 지원
- 로그 파일 자동 저장
- GitHub Actions 기반 자동 실행 지원

---

## Environment Variables

- `TEST_MODE=true`
  - 테스트 실행 시 요일/휴장일 체크를 우회합니다.
- `CUSTOM_WATCHLIST=TSM,ASML:ASML,Palantir:PLTR`
  - `티커` 또는 `표시명:티커` 형식으로 커스텀 종목을 지정합니다.
  - 브리핑에 `<b>커스텀 종목 브리핑</b>` 섹션이 자동 추가됩니다.

## Project Structure

```text
telegram_ai_USstock/
├─ main.py
├─ requirements.txt
├─ .env.example
├─ .gitignore
├─ logs/
└─ .github/
   └─ workflows/
      └─ us-close-briefing.yml

## Future Improvement
- 미국 휴장일 자동 인식
- 테스트 모드에서 요일 체크 우회
- 종목별 커스텀 브리핑
- 뉴스 품질 필터 강화
- Telegram 메시지 포맷 개선
- 섹터/산업 분류 확장
- HTML 메시지 스타일 개선
