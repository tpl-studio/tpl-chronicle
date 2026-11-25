# tpl-chronicle — 축구 왕국 연대기 릴스

축구 소식 하나를 '축구 왕국' 판타지 포스터(썸네일) + 15초 영상으로 만들어 개인 텔레그램 봇으로 보냅니다.

- 감시: Cloudflare Worker(tpl-live-watch)가 5분마다 새 기사를 보고, 후보가 있을 때만 이 저장소의 `chronicle` 워크플로를 부릅니다.
- 판단: 코드 1차 거르기 → Claude Haiku(터질 각 6항목) → 글·아트 시트 Claude → 그림 Gemini 1장(다시 그리기는 Cloudflare FLUX)
- 규칙: `prompts/tpl_chronicle_style.md` · 설정: `config/chronicle.toml` · 전설 명단: `config/legends.json`
- 상태(장 번호·본 소식·조회수·비용 장부): `chronicle-state` 브랜치
- 키는 저장소 Secrets 에만 둡니다(코드·커밋에 키 없음).

폰트: Black Han Sans (SIL Open Font License 1.1, `assets/fonts/OFL_BlackHanSans.txt`).
