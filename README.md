# 부동산 통합 모니터링 대시보드

아파트 실거래가 · 상가 · 토지 · 경매를 하나의 지도에서 보는 정적 웹 대시보드.

> © 2026 IEBKK. All rights reserved. 사전 서면 허가 없는 복제·수정·재배포·상업적
> 이용을 금합니다. 자세한 조건은 [LICENSE](LICENSE) 참고.
**서버도 DB도 없다.** GitHub Actions 가 매일 공공 API 를 긁어 JSON 으로 굽고,
정적 사이트가 그 JSON 만 읽는다. → 운영 비용 0원.

현재 상태: **M1(파이프라인) + M2(지도 MVP) + M3(유형 확장) 완료**.
아파트 · 상가 · 토지 실거래가와 온비드 공매를 제공한다.
추세 대시보드(M4)와 추천 엔진(M5)은 아직이다.

| 탭 | 소스 | 단위 | 비고 |
|---|---|---|---|
| 아파트 | 국토부 아파트 매매 실거래가 | 단지 (법정동×지번×단지명) | 면적 타입별 통계 |
| 상가 | 국토부 상업업무용 실거래가 | 건물 (법정동×지번×건물명) | 용도·용도지역·대지면적 |
| 토지 | 국토부 토지 실거래가 | 법정동×지목 | 지번 미제공이라 그 이상 쪼갤 수 없다 |
| 경매·공매 | 온비드(캠코) 공매 | 물건 | **법원경매 미포함** — 아래 참고 |

```
공공 API ──(매일 06:00 KST, GitHub Actions)──▶ web/public/data/*.json ──(정적 배포)──▶ 브라우저
```

---

## 빠른 시작 (API 키 없이)

```bash
# 1. 모의 데이터 생성 — 서울 25개 구, 최근 3개월, 4개 유형 전부
python3 -m pipeline.build --mock --no-geocode

# 2. 웹 실행
cd web && npm install && npm run dev
```

`--mock` 으로 만든 데이터는 상단에 **모의 데이터** 배지가 붙는다.

## 실제 데이터로 돌리기

1. [공공데이터포털](https://www.data.go.kr) 가입 후 아래를 활용신청 (승인 즉시 발급, 전부 무료).
   국토부 3종은 인증키 하나(`MOLIT_SERVICE_KEY`)를 공유한다.
   - 국토교통부 **아파트 매매 실거래가 상세 자료**
   - 국토교통부 **상업업무용 부동산 매매 신고 자료**
   - 국토교통부 **토지 매매 신고 조회 서비스**
   - 한국자산관리공사 **온비드 공매물건 정보** → `ONBID_SERVICE_KEY`

   호출량은 API 별로 `시군구 수 × 3개월`(+페이징). 전국 269개 시군구면 API 당 하루 약 810회로
   개발계정 한도(일 1,000회/API) 안이지만 여유가 15% 남짓이다. 재시도가 잦아 한도에 걸리면
   해당 API 의 운영계정(트래픽 증량)을 신청한다. 온비드는 전국을 한 번에 받으므로 수 회면 끝난다.
2. (선택) [VWorld](https://www.vworld.kr) 또는 [Kakao Developers](https://developers.kakao.com) 키 발급 → 정밀 좌표.
   없으면 시군구 중심 근사 좌표를 쓰고 UI 에 `위치 근사` 배지가 붙는다.
3. `.env.example` 을 참고해 환경변수 설정 후:

```bash
pip install -r pipeline/requirements.txt
MOLIT_SERVICE_KEY=... ONBID_SERVICE_KEY=... python3 -m pipeline.build

# 일부 유형·지역만
python3 -m pipeline.build --types apt,auction --regions 11680,11650
```

> 인증키는 **Decoding** 키를 쓴다. Encoding 키를 넣으면 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 가 난다.

## 저장소 구조

```
pipeline/               # 수집 → 집계 → JSON (Python 표준 라이브러리 + requests 만)
  build.py              #   진입점. --mock / --types / --regions / --no-geocode
  config.py             #   환경변수·시군구 목록·롤링 개월·주소→시군구 매칭
  sources/common.py     #   국토부 3종 공통 호출·파싱 (별칭 기반 필드 매핑)
  sources/molit_apt.py       #   아파트 매매
  sources/molit_commercial.py#   상업업무용
  sources/molit_land.py      #   토지
  sources/onbid.py           #   온비드 공매 (전국 1회 호출)
  transform.py          #   유형 공통 집계 + 공매 집계(최저가율·유찰·NEW)
  geocode.py            #   주소→좌표 (VWorld/Kakao) + 저장소 캐시 + 근사 폴백
  mock.py               #   API 키 없이 쓰는 합성 데이터 (4개 유형)
  seed/regions.json     #   시군구 코드 + 중심좌표 (전국 269개 시군구)
  scripts/make_regions.py #  법정동코드 전체자료(code.go.kr)로 seed 재생성
  cache/geocode.json    #   지오코딩 캐시 — 커밋 대상. 지우면 호출량이 폭증한다
  cache/auction_seen.json #  공매 물건 최초 관측일 — NEW 뱃지 판정 근거. 커밋 대상
  fixtures/             #   4종 API 응답 샘플 (구/신 필드 표기 혼재)
  tests/                #   python3 -m pipeline.tests.test_transform

web/                    # React + Vite + TS, Leaflet + supercluster + Recharts
  public/data/          #   파이프라인 산출물. 빌드 시 dist/data 로 그대로 복사된다
                        #   apt|commercial|land/{시군구코드}.json, auction/onbid.json,
                        #   summary/{유형}.json, meta.json, search-index.json
  src/hooks/useVisibleData.ts  # 화면 영역 → 필요한 시군구 JSON 만 lazy load
  src/components/MapView.tsx   # Leaflet 직접 제어 (클러스터링·마커)

.github/workflows/
  daily-data.yml        # cron 21:00 UTC = 06:00 KST → 수집 → 커밋 → deploy 호출
  deploy.yml            # GitHub Pages 배포 (workflow_call 로도 호출됨)
  ci.yml                # PR: 파이프라인 테스트 + 모의 빌드 + typecheck + web 빌드
```

## 배포 (GitHub Pages)

1. 저장소를 **public** 으로 만든다 (Actions 무제한).
2. Settings → Pages → Source 를 **GitHub Actions** 로.
3. Settings → Secrets and variables → Actions
   - Secrets: `MOLIT_SERVICE_KEY`, `ONBID_SERVICE_KEY`, (선택) `VWORLD_KEY`, `KAKAO_REST_KEY`
   - Variables: (선택) `GA_MEASUREMENT_ID` — 넣으면 GA4 스크립트가 주입된다
4. Actions 탭에서 `daily-data` 를 수동 실행해 첫 데이터를 만든다.

Cloudflare Pages 로 옮기려면 `deploy.yml` 만 교체하고 `VITE_BASE` 를 비우면 된다
(대역폭 무제한 + Web Analytics 무료).

## 설계 메모

**왜 시군구별로 JSON 을 쪼갰나** — 지도 화면에 걸친 구의 파일만 받으면 되므로,
전국으로 늘려도 첫 로딩은 `summary/nation.json` 하나(현재 21 KB)로 끝난다.
구 하나당 파일은 20~30 KB 수준이고, 빌드 시 1 MB 를 넘으면 경고가 찍힌다.

**왜 단지당 거래를 60건까지만 담나** — 파일 크기 상한 때문. 전체 이력이 필요해지면
`apt/{code}/{complexId}.json` 으로 한 단계 더 쪼개는 게 맞다.

**왜 최근 3개월을 매일 다시 받나** — 실거래 신고 기한이 계약 후 30일이라, 지난달 데이터가
이번 달에도 계속 늘어난다. 한 번 받고 끝내면 최근 두 달치가 영구히 비어 보인다.

**지오코딩 캐시가 핵심이다** — 실거래가 API 는 좌표를 주지 않는다. `pipeline/cache/geocode.json`
을 커밋해 두기 때문에 매일 새로 등장한 주소만 조회한다. 캐시를 지우면 무료 쿼터가 하루에 소진된다.
키가 없을 때 만들어진 근사 좌표는 `geo: "approx"` 로 표시된다. 나중에 키를 넣었다면
`--refresh-approx` 로 한 번 돌려 그 항목만 정밀 좌표로 승격시킨다
(남은 개수는 `meta.json` 의 `geocode.pendingExact`).

**국토부 API 는 주기적으로 개편된다** — 파서가 현행 camelCase(`dealAmount`)와 구버전
한글 태그(`거래금액`)를 모두 받는 이유다. 4종 픽스처에 두 형태가 섞여 있어
`pipeline/tests/test_transform.py` 가 회귀를 잡는다. 3종 국토부 API 는 호출 규약이 같아
`sources/common.py` 에 모으고, 각 소스는 '엔드포인트 + 필드 별칭 표'만 선언한다.

> 필드명은 실 응답으로 한 번 검증해야 한다. 키가 없어 픽스처 기준으로만 작성했으므로,
> 첫 실 수집 때 `meta.json` 의 `dealCountByType` 이 0 이면 별칭 표부터 확인하라.

**공매 NEW 뱃지는 우리가 판정한다** — 온비드 응답에 '신규' 플래그가 없다. 물건키별 최초 관측일을
`cache/auction_seen.json` 에 적어 두고 그날 처음 본 것만 NEW 로 표시한다. 종료된 물건 키는
매 실행마다 정리해 파일이 무한히 자라지 않게 한다.

**최저가율(최저입찰가 ÷ 감정가)이 공매의 핵심 지표다** — 유찰될 때마다 최저가가 깎이므로,
이 값이 낮을수록 유찰이 누적된 물건이다. 목록·지도 정렬 기준이자 M5 추천 엔진의 P0 시그널이다.

## 법원경매를 넣지 않은 이유

법원경매(courtauction.go.kr)에는 무료 공식 벌크 API 가 없다. PRD 3.2-D 의 3단계 전략을 따른다.

| 단계 | 소스 | 상태 |
|---|---|---|
| Phase 1 | 온비드 공매 API | **구현 완료** — 지금 경매·공매 탭에 나오는 것 |
| Phase 2 | 사법정보공유포털(openapi.scourt.go.kr) | 미착수 — 부동산 물건 목록 제공 여부 검증 필요 |
| Phase 3 | 상용 스크래핑 API (CODEF / 하이픈) | 유료. Phase 2 결과가 불충분할 때만, 비용 상한 승인 후 |

직접 크롤링은 채택하지 않는다 — 이용약관·법적 리스크와 봇 차단 유지보수 부담이
"비용 0원"보다 지속가능성을 더 해친다. 그래서 탭 이름은 '경매·공매'지만 현재 데이터는
**공매뿐**이며, 화면 상단에 그 범위를 고정 노출한다.

## 알려진 제약

- **행정구역은 2026년 개편 기준**(전남광주통합특별시 등)이다. 개편이 또 있으면
  `python -m pipeline.scripts.make_regions` 로 seed 를 재생성한다.
- **좌표가 근사값**이다. VWorld/Kakao 키를 넣기 전까지 마커는 구 중심에서 반경 900m 안에
  결정적으로 흩뿌려진다. 같은 단지는 항상 같은 자리에 찍히지만 실제 위치는 아니다.
- **매매만** 있다. 전월세는 별도 API 라 아직 붙이지 않았다.
- **토지는 지번이 없다.** 국토부 토지 API 가 법정동까지만 주므로 '법정동 × 지목' 이 최소 단위다.
  같은 동의 서로 다른 필지가 한 마커로 합쳐진다.
- **상가는 건물명이 자주 비어 온다.** 그럴 때 '건물주용도 + 지번'으로 표시명을 합성한다.
- **법원경매 미포함** (위 섹션 참고).
- 스케줄 워크플로는 저장소가 60일간 비활성이면 GitHub 이 자동 중지한다.
  매일 데이터 커밋이 들어가므로 정상 운영 중에는 문제되지 않는다.

## 법적 고지

정보는 참고용이며, 거래·입찰 전 원출처(국토교통부, 온비드, 법원) 확인이 필요하다.
출처: 국토교통부 실거래가 공개시스템(공공데이터포털). 지도 © OpenStreetMap 기여자.

이 저장소의 코드는 **All rights reserved** 다 — 열람용으로만 공개하며,
사전 허가 없는 복제·수정·배포·상업적 이용을 허용하지 않는다. [LICENSE](LICENSE) 참고.
