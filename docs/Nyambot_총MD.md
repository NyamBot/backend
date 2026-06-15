# NyamBot 총 정리 문서

## 1. 프로젝트 한 줄 소개

NyamBot는 사용자가 채팅으로 맛집을 물어보면, 저장된 맛집 메모와 리뷰성 텍스트를 기반으로 RAG + 하이브리드 검색 + Gemma rerank를 거쳐 근거 있는 맛집을 추천하는 웹 서비스이다.

예시 질문:

```text
성수에서 조용한 데이트 맛집 알려줘
홍대에서 혼밥하기 좋은 저렴한 식당 추천해줘
강남에서 회식하기 좋은 고기집 알려줘
근처에서 출출한데 가볍게 먹을 곳 알려줘
카페 가고 싶어
강남 말고 신림
```

## 2. 프로젝트 방향

기존 숏폼 마케팅 에이전트 방향에서 맛집 추천 웹 서비스로 전환했다.

핵심은 단순 AI 추천이 아니라, 저장된 맛집 데이터와 사용자의 방문 메모를 근거로 답변하는 RAG 기반 추천이다. 추천 후보는 백엔드가 넓게 수집하고, Gemma가 사용자 발화 의도를 해석해 후보 목록 안에서만 rerank한다.

## 3. 핵심 기술 키워드

- FastAPI
- React + Vite
- PostgreSQL
- pgvector
- Vector DB
- RAG
- Hybrid Search
- Gemma rerank
- Hugging Face Inference Providers
- Docker
- Kakao Local API
- Kakao Login
- JWT 인증/인가

## 4. MVP 핵심 기능

- 카카오 로그인 OAuth 플로우와 JWT 기반 사용자 세션
- 사용자별 맛집 메모 등록
- 저장된 맛집 목록 조회
- 기존 맛집에 방문 메모 추가
- 카카오 Local API 장소 검색
- SQL 필터, 태그 점수, 키워드 점수, 벡터 유사도, 위치 점수를 섞은 하이브리드 추천
- Gemma 기반 후보 rerank
- 추천 답변, 근거 메모, 추천 카드, 채팅 기록 저장
- SQLite 로컬 fallback과 PostgreSQL pgvector 인프라

## 5. MVP 기능 범위

### 5.1 맛집 데이터 등록

사용자가 직접 맛집 데이터를 등록한다.

입력 항목:

- 식당명
- 지역
- 음식 종류
- 가격대
- 분위기 태그
- 대표 메뉴
- 방문 메모/리뷰
- 카카오 장소 URL

처리 방식:

- 식당 기본 정보는 일반 DB 테이블에 저장
- 방문 메모/리뷰 텍스트는 임베딩 후 pgvector에 저장
- PostgreSQL 연결 실패 시 개발 편의를 위해 SQLite fallback 사용

### 5.2 맛집 추천 채팅

사용자가 자연어로 맛집을 질문한다.

백엔드는 다음 흐름으로 추천한다.

1. 지역/음식 종류/가격대 같은 명시 조건을 반영한다.
2. 저장 맛집, 근처 맛집, 카카오 장소 후보를 넓게 수집한다.
3. pgvector 유사도, 태그/키워드/위치 점수로 후보 기반 점수를 만든다.
4. Gemma rerank 프롬프트에 후보 목록을 넣고 후보 안에서만 선택하게 한다.
5. 백엔드가 Gemma가 반환한 `candidate_id`가 실제 후보에 있는지 검증한다.
6. 검증된 후보만 카드와 답변에 사용한다.

### 5.3 추천 결과 카드

추천 결과는 카드 형태로 보여준다.

표시 항목:

- 식당명
- 지역
- 음식 종류
- 가격대
- 추천 이유
- 근거 메모
- 추천 메뉴
- 주의사항
- 카카오 지도 링크
- 거리 정보가 있는 경우 현재 위치 기준 거리

최종 UX 방향은 카드 중심이다. AI 답변은 길게 풀기보다 카드 선택을 보조하는 짧은 요약 한 줄 중심으로 정리하는 방향이 좋다.

### 5.4 저장된 맛집 목록

등록된 맛집을 목록으로 확인한다.

표시 항목:

- 식당명
- 지역
- 음식 종류
- 태그
- 저장된 메모 개수

### 5.5 채팅 기록 저장

사용자의 질문과 AI 답변을 저장한다.

저장 항목:

- user message
- assistant message
- 답변에 사용된 근거 context
- 생성 시간

## 6. MVP에서 제외할 기능

초기 MVP에서는 아래 기능을 제외한다.

- 실시간 영업시간 확인
- 네이버/카카오 리뷰 크롤링
- 예약 기능
- 결제 기능
- 대량 CSV 업로드
- Google 로그인

## 7. 추후 확장 기능

### 7.1 Kakao Local API 고도화

사용자가 지역/키워드를 입력하면 카카오 Local API로 장소 후보를 검색한다.

예:

```text
성수 파스타
홍대 조용한 술집
신림 간단한 밥
근처 카페
```

카카오 API에서 가져올 수 있는 정보:

- 장소명
- 카테고리
- 주소
- 도로명 주소
- 좌표
- 전화번호
- 카카오 장소 URL

주의:

- 카카오 API는 장소 기본 정보 검색 용도로 사용
- 리뷰 본문은 카카오 API에서 가져오지 않음
- RAG에 사용할 텍스트는 사용자가 직접 입력한 메모/리뷰 위주로 저장
- 카카오 후보를 저장 기록처럼 말하지 않음

### 7.2 Kakao Login

카카오 소셜 로그인으로 사용자 계정을 연결한다.

흐름:

```text
프론트 로그인 버튼
→ 백엔드 /api/v1/auth/kakao/login
→ 카카오 로그인
→ 백엔드 /api/v1/auth/kakao/callback
→ 사용자 upsert
→ JWT 발급
→ 프론트로 redirect
→ 프론트에서 auth_code를 session token으로 교환
```

로컬 Redirect URI:

```text
http://127.0.0.1:8000/api/v1/auth/kakao/callback
```

프론트 로컬 URL:

```text
http://127.0.0.1:5173
```

### 7.3 사용자별 데이터 보호

로그인 구현 후 사용자별로 맛집/메모/채팅 기록을 분리한다.

FastAPI에서는 `Depends(get_current_user)` 형태로 보호한다.

## 8. 벡터 DB에는 무엇을 저장하는가

벡터 DB에는 식당 자체가 아니라, 식당에 대한 자연어 텍스트를 저장한다.

저장 대상:

- 방문 메모
- 리뷰성 텍스트
- 분위기 설명
- 메뉴 추천 메모
- 웨이팅/주차/소음 등 방문 팁

예:

```text
조명이 은은하고 테이블 간격이 넓어서 조용히 대화하기 좋았다.
소개팅이나 데이트에 잘 맞고, 주말 저녁에는 약간 웨이팅이 있었다.
```

이 텍스트를 임베딩 벡터로 바꿔 `restaurant_notes.embedding`에 저장한다.

## 9. 추천 검색과 Gemma rerank 흐름

### 9.1 백엔드 후보 수집

백엔드는 의미 판단을 Gemma에 맡기되, 후보 수집은 넓고 균형 있게 수행한다.

수집 대상:

- 사용자가 저장한 맛집
- 지역/음식 종류/가격대 조건에 맞는 저장 맛집
- 현재 위치 기준 근처 저장 맛집
- 저장 맛집이 부족할 때 Kakao Local API 후보
- 사용자 발화에서 유추한 지역/카테고리 키워드 기반 Kakao Local API 후보

후보 수집 품질 개선 방향:

- 카카오 검색어가 한 카테고리에 몰리지 않도록 다변화
- 카페, 간단히, 든든하게, 술 없이, 웨이팅 적은 같은 발화별 검색 후보 균형 확인
- 저장 맛집과 카카오 후보가 섞일 때 source를 명확히 구분
- 저장 메모가 있는 후보는 태그, 가격대, 방문 기록, 메모를 더 풍부하게 전달

### 9.2 pgvector 후보 검색

PostgreSQL을 사용할 때는 `restaurant_notes.embedding`을 pgvector로 저장하고, 채팅 추천 시 DB에서 `<=>` 벡터 거리 기준으로 후보를 먼저 가져온다.

추천 검색은 하이브리드 방식이다.

- pgvector 유사도 검색: 저장된 맛집 메모와 사용자 질문의 벡터 거리를 비교
- 메타데이터 필터: 사용자, 음식 종류, 가격대, 지역 조건 반영
- 태그 점수: 저장 태그와 분위기 태그 보정
- 키워드 점수: 메모/식당 정보의 키워드 매칭 보정
- 위치 점수: 위치 반영이 켜져 있으면 현재 위치와 맛집 좌표의 거리 반영
- 근방 fallback: 현재 위치 근방에 저장된 맛집 후보가 없으면 카카오 장소 검색으로 주변 후보를 가져옴

기본 점수 예시:

```text
score = vector_score + tag_score + keyword_score + location_score
```

### 9.3 Gemma rerank 프롬프트

Gemma rerank는 후보 목록 안에서만 선택해야 한다.

rerank 프롬프트 요구사항:

- 후보 목록 밖 식당 선택 금지
- 사용자 발화 의도 분석
- 지역 조건 준수
- 현재 위치/거리 정보 반영
- 혼밥/출출함/데이트/회식/카페/가볍게/든든하게/술 없이/웨이팅 적은 같은 의미 판단
- 카카오 후보와 저장 맛집 후보를 구분
- JSON으로 `candidate_id` 3개 반환

응답 형식 예시:

```json
{
  "candidate_ids": ["saved-restaurant-1", "kakao-venue-7", "saved-restaurant-3"]
}
```

### 9.4 후보별 거리 정보 강화

Gemma가 위치를 더 잘 판단하도록 후보별 거리 계산값을 명확히 넣는다.

예:

```text
- candidate_id: saved-restaurant-1
  name: 성수면옥
  source: saved
  area: 성수
  distance_from_user: 0.3km
  note: 혼밥하기 편하고 회전이 빠름

- candidate_id: kakao-venue-7
  name: 성수카페
  source: kakao
  area: 성수
  distance_from_user: 1.4km
  kakao_category: 카페
```

### 9.5 백엔드 검증

백엔드는 Gemma rerank 결과를 그대로 믿지 않는다.

검증 규칙:

- 반환된 `candidate_id`가 실제 후보 목록에 있는지 확인
- 후보 목록 밖 ID는 버림
- JSON 파싱 실패 또는 이상 응답이면 fallback 사용
- 후보 수가 부족하면 백엔드 점수 순 fallback 사용
- fallback 동작은 로그로 남겨 품질을 확인

### 9.6 Gemma 답변 프롬프트

답변 프롬프트는 검증된 후보만 설명한다.

답변 프롬프트 요구사항:

- 검증된 후보만 설명
- 후보 밖 식당 언급 금지
- 카카오 후보를 저장 기록처럼 말하지 않기
- 저장 맛집은 저장 메모/태그/가격대/방문 기록을 근거로 설명
- 카카오 후보는 카카오 장소 정보 기반 후보라고 표현
- 카드 중심 UX에 맞게 짧고 구체적으로 설명

## 10. Gemma / Hugging Face AI 설정

맛집 채팅 답변과 rerank는 Hugging Face Inference Providers의 chat completions API를 사용할 수 있다.

로컬 `.env.dev`에는 아래 값을 설정한다. `.env` 파일은 Git에 올리지 않는다.

```text
HF_TOKEN=hf_...
HUGGINGFACE_CHAT_MODEL=google/gemma-4-26B-A4B-it:featherless-ai
HUGGINGFACE_CHAT_BASE_URL=https://router.huggingface.co/v1
```

Gemma 4 계열 중 Hugging Face chat completions 라우터에서 확인한 모델 예시는 아래와 같다.

```text
google/gemma-4-26B-A4B-it:featherless-ai
google/gemma-4-31B-it:featherless-ai
```

HF 실패 시 fallback:

- `HF_TOKEN`이 없으면 AI 호출 없이 기존 템플릿/fallback 답변 사용
- Hugging Face 호출 실패 시 백엔드 점수 기반 후보 순서 사용
- JSON rerank 파싱 실패 시 백엔드 점수 기반 후보 순서 사용
- 이상 응답과 fallback 발생 케이스는 로그로 확인

## 11. 위치/지역 충돌 정책

지역 조건과 현재 위치 조건이 충돌할 수 있으므로 정책을 고정한다.

- 사용자가 명시 지역을 말하면 명시 지역 우선
- 예: 현재 위치는 방배지만 "성수 맛집"이라고 하면 성수 우선
- 사용자가 "근처", "주변", "가까운 곳"이라고 말하면 현재 위치 우선
- 사용자가 "강남 말고 신림"처럼 제외/선호 지역을 함께 말하면 제외 지역을 피하고 선호 지역 우선
- 현재 위치 좌표가 없으면 지역/카테고리/저장 메모 기준으로 추천

## 12. 테스트 케이스

Gemma rerank와 후보 수집 품질을 고정 테스트로 확인한다.

우선순위 높은 테스트:

- 성수 혼밥
- 신림 간단하게 먹을 곳
- 관악 데이트
- 근처에서 출출한데 가볍게
- 카페 가고 싶어
- 강남 말고 신림
- 술 없이 이야기하기 좋은 곳
- 웨이팅 적은 곳
- 든든하게 먹고 싶어

검증 포인트:

- JSON rerank가 정상 파싱되는지
- `candidate_id`가 실제 후보에 있는지
- 후보 밖 식당이 답변에 나오지 않는지
- 카페 발화에서 음식점 후보만 몰리지 않는지
- "근처" 발화에서 거리 정보가 반영되는지
- 명시 지역이 현재 위치보다 우선되는지
- 저장 맛집과 카카오 후보를 답변에서 구분하는지

## 13. 저장 맛집 RAG 강화 방향

저장 메모가 있는 후보는 카카오 후보보다 더 잘 설명되게 만든다.

강화할 정보:

- 저장 메모
- 태그
- 가격대
- 대표 메뉴
- 방문 기록
- 웨이팅/주차/소음 팁
- 혼밥/데이트/회식 같은 상황 태그

Gemma rerank 프롬프트에는 저장 맛집 후보의 근거를 더 풍부하게 넣고, 카카오 후보는 장소 기본 정보만 제공한다.

## 14. DB ERD

```mermaid
erDiagram
    users ||--o{ restaurants : owns
    restaurants ||--o{ restaurant_notes : has
    users ||--o{ taste_agent_messages : chats

    users {
        string id PK
        string email
        string display_name
        string avatar_url
        string auth_provider
        string provider_subject
        datetime created_at
        datetime last_login_at
    }

    restaurants {
        string id PK
        string user_id FK
        string name
        string area
        string cuisine
        string price_level
        json mood_tags_json
        json signature_menus_json
        string kakao_place_id
        string kakao_place_url
        string address
        string road_address
        string phone
        datetime created_at
    }

    restaurant_notes {
        string id PK
        string restaurant_id FK
        text content
        json tags_json
        vector embedding
        datetime created_at
    }

    taste_agent_messages {
        string id PK
        string user_id FK
        string role
        text content
        json retrieved_context_json
        datetime created_at
    }
```

## 15. Backend API

### 15.1 Health

```http
GET /health
```

### 15.2 Users

```http
POST /api/v1/users
GET /api/v1/users
GET /api/v1/users/{user_id}
```

### 15.3 Auth

```http
GET /api/v1/auth/kakao/login
GET /api/v1/auth/kakao/callback
POST /api/v1/auth/session
GET /api/v1/auth/me
```

### 15.4 Restaurants

```http
POST /api/v1/restaurants
GET /api/v1/restaurants
GET /api/v1/restaurants/{restaurant_id}
PUT /api/v1/restaurants/{restaurant_id}
DELETE /api/v1/restaurants/{restaurant_id}
POST /api/v1/restaurants/{restaurant_id}/notes
```

### 15.5 Kakao Local

```http
GET /api/v1/restaurants/kakao/search
GET /api/v1/restaurants/kakao/validate?query=성수 맛집
```

### 15.6 Recommendations

```http
POST /api/v1/restaurants/recommendations
```

Request 예시:

```json
{
  "query": "성수에서 조용한 데이트 맛집 추천해줘",
  "area": "성수",
  "cuisine": "일식",
  "price_level": "보통",
  "tags": ["조용함", "데이트"],
  "limit": 3
}
```

### 15.7 Taste Agent Chat

```http
POST /api/v1/restaurants/chat
GET /api/v1/restaurants/chat/messages
GET /api/v1/restaurants/chat/sessions
```

Request 예시:

```json
{
  "query": "성수 맛집",
  "message": "성수에서 조용한 데이트 맛집 알려줘",
  "area": "성수",
  "tags": ["조용함", "데이트"],
  "limit": 3
}
```

## 16. 패키지 구조

### 16.1 Backend

```text
NyamBot_Backend/
  app/
    main.py
    core/
      config.py
      dependencies.py
      security.py
    routers/
      auth.py
      users.py
      restaurants.py
    services/
      auth_exchange.py
      huggingface_chat.py
      kakao_auth.py
      kakao_local.py
      restaurant_store.py
    schemas.py
  infra/
    pgvector/
      Dockerfile
  docker-compose.pgvector.yml
  nyambot.local.yml
  requirements.txt
  requirements-db.txt
```

### 16.2 Frontend

```text
NyamBot_Frontend/
  src/
    App.tsx
    api.ts
    main.tsx
    index.css
    auth/
      AuthContext.tsx
    components/
      KakaoMap.tsx
      Logo.tsx
      Mascot.tsx
      RestaurantMap.tsx
      ui.tsx
      layout/
        AppLayout.tsx
    data/
      koreaRegions.ts
    lib/
      kakaoMap.ts
      utils.ts
    pages/
      ChatPage.tsx
      HistoryDetailPage.tsx
      HistoryPage.tsx
      LoginPage.tsx
      RestaurantDetailPage.tsx
      RestaurantFormPage.tsx
      RestaurantMapPage.tsx
      RestaurantsPage.tsx
    routes/
      ProtectedRoute.tsx
  public/
    dev-login.html
    favicon.svg
    nyambot-logo.png
  index.html
  package.json
  nyambot.local.yml
  vite.config.ts
```

## 17. 로컬 포트 고정

로컬 개발 포트는 아래 값으로 고정한다.

```text
frontend: http://127.0.0.1:5173
backend: http://127.0.0.1:8000
database: localhost:15432
```

포트 고정 설정 파일:

```text
backend/nyambot.local.yml
frontend/nyambot.local.yml
```

프론트는 `vite.config.ts`에서 `strictPort: true`로 설정한다.

## 18. 로컬 실행

DB:

```powershell
cd backend
docker compose -f docker-compose.pgvector.yml up -d --build
```

Backend:

```powershell
cd backend
APP_ENV=dev python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## 19. Docker / pgvector

현재 Docker 인프라 이름:

```text
image: nyambot-pgvector:latest
container: nyambot-pgvector
volume: nyambot-pgvector-data
```

실행:

```powershell
docker compose -f docker-compose.pgvector.yml up -d --build
```

로컬 DB URL:

```text
postgresql://nyambot:nyambot@localhost:15432/nyambot
```

PostgreSQL 연결에 실패하면 앱은 개발 편의를 위해 SQLite fallback으로 동작한다. 이때 `/health`의 `vector_store` 값이 `sqlite-vector`로 표시된다.

## 20. Env 관리

실제 env 파일은 git에 올리지 않는다.

무시 대상:

```text
.env*
```

백엔드:

- `.env.dev`
- `.env.prod`
- `API_PREFIX=/api/v1`

프론트:

- `.env.dev`
- `.env.prod`
- `VITE_API_PREFIX=/api/v1`

프론트 Vite script:

```json
{
  "dev": "vite --mode dev",
  "build:dev": "tsc -b && vite build --mode dev",
  "build:prod": "tsc -b && vite build --mode production"
}
```

## 21. 검증

Backend import smoke:

```powershell
cd backend
python -m compileall app
python -c "from app.main import app; print(app.title)"
```

Frontend build:

```powershell
cd frontend
npm run build
```

브라우저 E2E 체크:

- 로그인 전 추천/저장 버튼이 비활성화되거나 로그인 안내가 표시되는지 확인
- 카카오 로그인 버튼이 `/api/v1/auth/kakao/login`으로 이동하는지 확인
- 장소 검색에서 `KAKAO_LOCAL_REST_API_KEY` 누락 또는 오류 메시지가 노출되는지 확인
- 로그인 후 샘플 맛집 저장, 추천 질문, 추천 카드, 채팅 기록 저장 흐름 확인
- Gemma rerank 실패/이상 응답 시 fallback이 자연스러운지 확인

## 22. Git 브랜치 전략

### 22.1 브랜치 역할

- `main`: 배포 및 최종 안정 브랜치
- `dev`: 다음 배포를 준비하는 통합 브랜치
- `feat-<숫자>`: 기능 작업 브랜치. 예시는 `feat-001`, `feat-002`

### 22.2 새 작업 브랜치 생성

새 기능 브랜치는 항상 최신 `dev`에서 생성한다.

```powershell
git switch dev
git pull --rebase origin dev
git switch -c feat-001
```

기능 번호는 사용 가능한 다음 번호를 사용한다. 프론트엔드와 백엔드를 같은 작업에서 함께 수정하면 두 저장소의 기능 브랜치 번호를 동일하게 맞춘다.

### 22.3 dev 병합 전 준비

기능 브랜치를 `dev`에 병합하기 전에 최신 `dev` 기준으로 rebase한다.

```powershell
git switch dev
git pull --rebase origin dev
git switch feat-001
git rebase dev
```

이미 원격에 올린 브랜치를 rebase했다면 아래 명령으로 원격 브랜치를 갱신한다.

```powershell
git push --force-with-lease origin feat-001
```

### 22.4 feat -> dev 병합 규칙

공통 기준:

- 기능 브랜치는 `dev` 기준으로 rebase한 뒤 `--no-ff` merge로 `dev`에 병합
- 기능 브랜치의 흐름을 Git 그래프에서 볼 수 있음
- 문제가 생겼을 때 merge commit revert로 롤백하기 쉬움

```powershell
git switch dev
git pull --rebase origin dev
git switch feat-001
git rebase dev
git switch dev
git merge --no-ff feat-001 -m "feat: 작업 내용을 dev에 병합"
git push origin dev
```

### 22.5 dev -> main 배포 병합 규칙

`dev` 검증이 끝나면 `main`으로 배포한다.

병합 전에는 `dev` 브랜치에서 `git rebase main`을 실행한다.

```powershell
git switch main
git pull --rebase origin main
git switch dev
git pull --rebase origin dev
git rebase main
```

그 다음 `main`에서 squash merge로 하나의 커밋만 남긴다.

```powershell
git switch main
git merge --squash dev
git commit -m "chore: dev 변경사항을 main에 반영"
git push origin main
```

`dev -> main` squash 커밋 메시지에는 배포 날짜와 스쿼시 대상 커밋 내역을 본문에 적는다.

예시:

```text
chore: 26.06.07 커밋 내역 스쿼시

feat: 위치 기반 맛집 추천과 지도 기능 추가
chore: use dev env mode
chore: remove env example files
```

### 22.6 커밋 메시지 규칙

커밋 메시지는 한국어로 작성하고, 변경 내용을 한 줄로 간단히 적는다.

형식:

```text
type: 변경 내용
```

사용 가능한 타입:

- `feat`: 새로운 기능 추가
- `fix`: 버그 수정
- `docs`: 문서 수정
- `style`: 코드 포맷팅, 세미콜론 누락, 코드 변경이 없는 경우
- `refactor`: 코드 리팩토링
- `test`: 테스트 코드, 리팩토링 테스트 코드 추가
- `chore`: 빌드 업무 수정, 패키지 매니저 수정

예시:

```text
feat: 맛집 검색 API를 추가
fix: 로그인 토큰 만료 오류를 수정
docs: 브랜치 전략 문서를 추가
refactor: 사용자 인증 로직을 분리
chore: 프론트엔드 패키지 설정을 정리
```

## 23. 현재 구현 상태

완료:

- NyamBot 리브랜딩
- 맛집 등록 API
- 맛집 목록 API
- 맛집 추천 API
- 맛집 채팅 API
- 채팅 기록 저장
- 채팅 세션 목록/상세 UI
- pgvector Docker 인프라
- 프론트 NyamBot 채팅 UI
- 추천 결과 카드 UI
- 저장된 맛집 목록 UI
- 맛집 수정/삭제 API와 UI
- 저장 맛집 지도 화면
- 식당 상세 지도 표시
- 현재 위치 기반 지도/추천 보조 흐름
- dev/prod env 분리
- Kakao Local API 장소 검색 API
- 기존 식당에 메모 추가 API
- Kakao Login
- JWT 인증/인가
- 카카오 Local REST API 키 검증 API
- README/발표 문서 정리
- 기존 ClipForge 숏폼 코드 정리
- 포트 고정 yml 추가
- Hugging Face/Gemma 모델 설정
- Gemma rerank JSON 응답 흐름
- rerank candidate_id 백엔드 검증
- Gemma rerank/답변 실패 metadata 저장
- 후보별 위치 좌표와 거리 정보 기본 반영
- 카카오 후보 수집 기본 검색어 다변화
- 위치/지역 충돌 정책 일부 구현
- 후보 밖 식당 금지 답변 프롬프트
- 저장 맛집과 카카오 후보 구분 정책

남은 작업:

- Gemma rerank 실패/이상 응답 metadata 기반 QA 확인
- rerank fallback 품질 확인
- 후보별 거리 정보를 `distance_from_user`처럼 명시적인 필드로 전달하는 프롬프트 개선
- 카페/간단히/든든하게/웨이팅 적은 곳 등 발화별 카카오 후보 수집 품질 개선
- 짧은 요약 한 줄 UX 확정
- 실제 브라우저 클릭 E2E 테스트
- 실제 카카오 개발자 앱 키로 OAuth 콜백 운영 검증
- 위치/지역 충돌 정책 테스트 고정
- 저장 맛집 RAG 강화

## 24. 발표 요약

NyamBot의 차별점은 일반적인 AI 추천이 아니라 사용자가 직접 쌓은 방문 메모를 검색 근거로 삼는다는 점이다. 식당 기본 정보는 테이블로 관리하고, 방문 메모는 임베딩해 벡터 검색 대상으로 저장한다.

추천 시 지역/음식 종류/가격대 같은 명시 조건은 SQL로 좁히고, 분위기 태그와 자연어 메모 유사도를 함께 계산해 후보를 만든다. 이후 Gemma rerank가 사용자 발화 의도, 현재 위치, 거리, 상황 의미를 판단해 후보 목록 안에서만 최종 후보를 고른다.

현재 MVP는 맛집 등록, 카카오 장소 검색, 사용자별 JWT 보호, 하이브리드 추천, Gemma rerank, 추천 카드 UI, 채팅 기록 저장, 지도 화면, 식당 상세/수정/삭제, 채팅 세션 조회까지 구현되어 있다. 추후에는 rerank 테스트 케이스 고정, 후보 수집 품질 개선, 영업시간 확인, 데이터 업로드 기능으로 확장할 수 있다.
