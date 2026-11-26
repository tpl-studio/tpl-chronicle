"""축구 왕국 연대기 — 기사 1개 → 요약 → 썸네일 글 시안 3개 → 아트 디렉션 시트 → Gemini 그림 1장 → 기준 디자인 합성 → 15초 영상 → 개인 봇.

규칙: prompts/tpl_chronicle_style.md. 매일 자동 실행은 사용자가 켜라고 할 때만(이 파일은 수동 실행용 함수 — 예약·감시기에 연결하지 않음).
실시간 카드뉴스 코드(transfer_news · hot_issue · romano · hwg_live)는 읽기만 해서 씀(수정 금지).
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

from . import art, chronicle as C, sources

STYLE = Path(__file__).resolve().parents[1] / "prompts" / "tpl_chronicle_style.md"
IMAGE_MODEL = "gemini-3.1-flash-image-preview"
CAP_KRW = 500.0
SYS = ("너는 한국 축구 SNS 'TPL'의 '축구 왕국 연대기' 편집장이다. 기사에 있는 사실만 쓴다. 숫자·이름은 2개 이상 매체에 나온 것만. "
       "조롱·비하 금지, 루머 단정 금지. JSON 만 답한다.")
EXCL = re.compile(r"1[0-7]세|under-1[0-7]|U-?1[0-7]\b|십자인대|시즌 아웃|수술|사망|별세|숨져|음주|성범죄|폭행|체포|기소|도박|마약|의혹|열애|결혼|이혼", re.I)


def _rules(sec_from: str, sec_to: str) -> str:
    md = STYLE.read_text(encoding="utf-8")
    return md.split(sec_from)[1].split(sec_to)[0]


# ── 1) 후보: 기존 피드(읽기만) + 로마노 본인 게시물 확인(읽기만)
def candidates(log=print) -> list[dict]:
    from . import feeds as FD
    hi = LR = tn = FD
    conf = tn.load_conf()
    now = tn.now_kst()
    items = tn.collect(conf, log=lambda m: None)
    rel = []
    for it in items:
        t = f"{it.get('title', '')} {it.get('summary', '')}"
        try:
            age = (now - datetime.fromisoformat(it.get("published", ""))).total_seconds() / 3600
        except (TypeError, ValueError):
            continue
        if age <= 24 and not tn.is_personal(t) and not EXCL.search(t):
            rel.append({**it, "category": "해외축구"})
    hwg_titles = set()
    try:                                                   # 1순위: 로마노 본인 'here we go' 게시물(실시간 카드뉴스 확인 방식 재사용)
        for p in FD.romano_posts(items, set(), limit=6):
            hwg_titles.add((p.get("text") or p.get("title") or "")[:120])
    except Exception as e:  # noqa: BLE001
        log(f"[연대기] 로마노 확인 실패: {type(e).__name__}")
    out = []
    for g in hi.cluster(rel, 0.30):
        outlets = list(dict.fromkeys(a.get("publisher", "") for a in g if a.get("publisher")))
        cred = [o for o in outlets if LR.credible(o) or hi.is_major(o, conf)]
        if len(cred) < 2:
            continue
        text = " ".join(a["title"] for a in g)
        out.append({"titles": [f"[{a.get('publisher', '')}] {a['title']}" for a in g][:12], "outlets": outlets, "credible": cred,
                    "stars": LR.stars(text) + LR.managers(text), "clubs": LR.big_clubs(text),
                    "hwg": any(h and h[:40].lower() in text.lower() for h in hwg_titles) or bool(re.search(r"here we go", text, re.I)),
                    "latest": max((a.get("published", "") for a in g), default="")})
    out.sort(key=lambda c: (5 * c["hwg"] + len(c["credible"]) + 2 * bool(c["stars"]) + 2 * bool(c["clubs"]), c["latest"]), reverse=True)   # 같은 점수면 최신
    return out[:15]


def pick(cands: list[dict], meter: art.Meter, today_subjects: list[str]) -> dict | None:
    lst = "\n\n".join(f"#{i}{' [로마노 HERE WE GO 확인]' if c['hwg'] else ''} (매체 {len(c['outlets'])}곳)\n" + "\n".join(c["titles"][:6])
                      for i, c in enumerate(cands))
    p = (f"[최근 24시간 축구 소식 후보]\n{lst}\n\n[고르는 기준]\n{_rules('## 4.', '## 5.')}\n"
         f"오늘 이미 만든 주인공·팀(같은 날 1편): {', '.join(today_subjects) or '없음'}\n"
         "좋은 소식이 없으면 pick 에 -1. ※ i·pick·best 는 0부터 시작하는 숫자만(태그 이름·매체 이름·글자 쓰지 말 것).\n"
         'JSON: {"pick": 번호, "subject_ko": "", "subject_en": "", "team_ko": "", "team_en": "", "league_ko": "", "role": "선수|감독", '
         '"kind": "로마노 이적|몰락·위기|충성·잔류|서러움·이탈|이적+위트|경질|갈등·유머|소방수|오심·징계|기록|기타", "rumor": false, "why": "", '
         '"queries_ko": ["",""], "queries_en": ["",""]}')
    from . import safe
    out = safe.ask_valid(lambda: art.claude_json(SYS, p, meter, "기사 고르기(Claude)"), safe.v_pick, {"pick": -1}, "기사 고르기")
    i = safe.as_index(out.get("pick"), len(cands), default=0, allow_none_pick=True)   # 숫자 아니면 0번 · 음수면 고를 것 없음
    if i is None:
        return None
    out["pick"] = i
    out["cand"] = cands[i]
    return out


LEGENDS = Path(__file__).resolve().parents[1] / "config" / "legends.json"


def legend_of(subject_ko: str, subject_en: str) -> str:
    """'전설'(선수) · '대원수'(감독) · ''."""
    try:
        lg = json.loads(LEGENDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    t = f"{subject_ko} {subject_en}".lower()
    for kind, rank in (("players", "전설"), ("managers", "대원수")):
        for p in lg.get(kind, []):
            if p["ko"] in subject_ko or any(n.lower() in t for n in p.get("en", []) if len(n) > 3):
                return rank
    return ""


def write(pk: dict, meter: art.Meter, mythic_ok: bool = False) -> dict:
    arts = sources.search(pk["queries_ko"] + pk["queries_en"], hours=36)
    names = [n.strip().split()[-1].lower() for n in (pk["subject_ko"].split("&") + pk["subject_en"].split("&")) if n.strip()]
    arts = [a for a in arts if any(n in (a["title"] + a["summary"]).lower() for n in names)]
    base = [{"outlet": t.split("]")[0].strip("["), "title": t.split("] ", 1)[-1], "summary": ""} for t in pk["cand"]["titles"]]
    if pk.get("body") and base:                     # 직접 요청: 보내 준 기사 본문을 첫 자료로
        base[0]["summary"] = pk["body"][:600]
    seen, uniq = set(), []
    for a in base + [{"outlet": a["outlet"], "title": a["title"], "summary": a["summary"][:300]} for a in arts]:
        k = re.sub(r"\W", "", a["title"].lower())[:40]
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    src = "\n".join(f"- [{a['outlet']}] {a['title']}" + (f" — {a['summary']}" if a["summary"] else "") for a in uniq[:35])
    lg = legend_of(pk["subject_ko"], pk["subject_en"])
    p = (f"주인공: {pk['subject_ko']} ({pk['subject_en']}) · 팀: {pk['team_ko']} ({pk['team_en']}) · 리그: {pk.get('league_ko', '')} · {pk['role']} · "
         f"종류: {pk['kind']} · 루머: {pk['rumor']}\n"
         f"legends.json: {lg or '해당 없음'} · 신화(날개·빛기둥) 이번 달 사용 가능: {'예(은퇴·역대급 기록 소식일 때만)' if mythic_ok else '아니오'}\n\n"
         f"[여러 매체 기사]\n{src}\n\n[썸네일 글 규칙 — 세계관 말은 쓰지 말 것(기사 사실 그대로)]\n{_rules('## 2.', '## 3.')}\n"
         f"[세계관 바이블 — 아트 시트(sheet)와 prompt_en 에만 적용]\n{_rules('## 5.', '## 6.')}\n"
         f"[아트 디렉션 시트]\n{_rules('## 6.', '## 7.')}\n[그림 프롬프트]\n{_rules('## 7.', '## 8.')}\n"
         "JSON 으로: facts[{fact, outlets[]}] 4~6개 · summary(3줄 이내) · drafts 3개[{tag, lines(2~3줄), name, score{hook,accuracy,rhythm,emotion}, note}] · "
         "best · why · sheet{continent(대륙), rank(신분 — 주장·신예·골키퍼는 기사에서 확인될 때만, 모르면 기사), event_scene(사건 장면), "
         "concept, emotion, face, pose, costume, costume_why, background{front,middle,back}, light_color, hidden_detail, looks} · "
         "prompt_en · question(편이 갈리는 질문 1줄) · facts2(캡션용 기사 핵심 2줄) · pinned(고정 댓글용 사실 1줄) · hashtags(5개: 선수·팀·리그·해외축구·축구릴스)\n"
         "drafts 의 tag·lines·name 은 모두 한국어(기사 영어 원문을 옮기지 말고 한국어로 요약 · 한 줄 9~12자 안팎) · name 은 국내 매체 한국어 표기 · "
         "tag 는 HERE WE GO(로마노 HWG 일 때만)·RUMOR(이적 아닌 소식의 루머만)·오피셜(구단·리그·협회 공식 발표일 때만 — 경기 결과·활약·출전 기사는 금지)·BBC 중 하나 또는 빈칸.\n"
         "lines 는 자연스러운 한국어 문장 — 'X득' 같은 기호·줄임말·영어 섞기 금지(무득점·공격포인트 없이처럼 풀어 쓰기).\n"
         "best 는 drafts 안 시안 번호(0, 1, 2 중 숫자 하나). ※ i·pick·best 는 0부터 시작하는 숫자만(태그 이름·매체 이름·글자 쓰지 말 것).")
    from . import safe
    out = safe.ask_valid(lambda: art.claude_json(SYS, p, meter, "요약·글·시트(Claude)"), safe.v_write, None, "요약·글·시트")
    if out is None:
        raise RuntimeError("요약·글·시트 형식이 두 번 다 틀림 → 이 기사는 건너뜀")
    out["best"] = safe.as_index(out.get("best"), len(out["drafts"]), out["drafts"], "tag", default=0)
    out["sources"] = list(dict.fromkeys(a["outlet"] for a in uniq))
    out["articles"] = uniq[:35]
    return out


def image(prompt: str, team_en: str, meter: art.Meter, what: str = "그림(Gemini)") -> tuple[bytes, str]:
    """Gemini 3.1 flash image · 9:16 2K. style_refs 에 그림이 있으면 화풍 참고로 같이(얼굴·날개는 따라 하지 않게)."""
    must = ["accurate real likeness", "face clearly visible, front or three-quarter view (never from behind)", f"real {team_en} kit visible between armor pieces", "ultra detailed skin, metal and fur textures",
            "sharp logos", "only one main costume, one background and one symbolic prop so the person stays clearly visible",
            "No text, no stadium name signs"]
    if not re.search(r"우승|champions?\b(?!\s*league)|won the (league|title|cup|final)|title[- ]winn", prompt, re.I):
        must.append("No trophy, no cup, no chalice, no winner's medal anywhere in the image (not a title win)")
    for s in must:
        if s.lower() not in prompt.lower():
            prompt = prompt.rstrip(". ") + ". " + s + "."
    refs = sorted(p for p in C.STYLE_REFS.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))[:3] if C.STYLE_REFS.exists() else []
    parts = []
    for r in refs:
        mime = "image/png" if r.suffix.lower() == ".png" else "image/webp" if r.suffix.lower() == ".webp" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(r.read_bytes()).decode()}})
    if refs:
        prompt = ("The attached images are STYLE references only: copy their painting style, colour grade, texture and composition. "
                  "Do NOT copy their faces, people or wings. ") + prompt
    meter.check(art.EST_IMAGE_KRW + 10 * len(refs), what)
    key = art._key()
    body = {"contents": [{"role": "user", "parts": parts + [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16", "imageSize": "2K"}}}
    r = requests.post(f"{art.URL}/{os.environ.get('GEMINI_IMAGE_MODEL', IMAGE_MODEL)}:generateContent",
                      headers={"x-goog-api-key": key, "content-type": "application/json"}, json=body, timeout=300)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if j.get("usageMetadata"):
        meter.add(art._image_cost(j["usageMetadata"]), what)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini 그림 HTTP {r.status_code}")
    for p in ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
        d = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
        if d:
            return base64.b64decode(d), prompt
    raise RuntimeError("Gemini 그림 거절")


def flux_redraw(w: dict, team_en: str) -> bytes:
    """다시 그리기(무료): Cloudflare FLUX 9:16 — 얼굴이 안 보이는 뒷모습·실루엣으로 같은 의상·배경·조명. 실패하면 1번 더."""
    acc, tok = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip(), os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not acc or not tok:
        raise RuntimeError("Cloudflare 키 없음")
    sh = w.get("sheet") or {}
    bg = sh.get("background") or {}
    prompt = ("Epic cinematic sports fantasy poster, vertical 9:16, photorealistic. A football figure seen from behind as a dark silhouette "
              f"(face not visible), heroic pose, wearing a {team_en} coloured kit under fantasy armour: " + str(sh.get("costume") or "")
              + ". Background: " + " / ".join(str(v) for v in bg.values()) + ". Lighting: " + str(sh.get("light_color") or "")
              + ". Ultra detailed textures, dramatic film lighting. No text, no letters, no logos, no signs.")
    last = ""
    for _ in range(2):
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-2-klein-9b",
                          headers={"Authorization": f"Bearer {tok}"},
                          files={"prompt": (None, prompt[:2000]), "width": (None, "1088"), "height": (None, "1920"), "steps": (None, "4")}, timeout=180)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            return r.content
        if r.status_code == 200:
            img = ((r.json() or {}).get("result") or {}).get("image")
            if img:
                return base64.b64decode(img)
        last = f"HTTP {r.status_code}"
    raise RuntimeError("FLUX 실패 " + last)


def _small_jpeg(png: bytes, side: int = 1024) -> bytes:
    """그림 점검용: 2K PNG 는 Claude 그림 크기 한도를 넘어 BadRequest(2026-11-26) → 긴 변 1024 JPEG 로 줄여 보냄."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def check_image(png: bytes, w: dict, pk: dict, meter: art.Meter) -> dict:
    """그림 점검(Claude 가 그림을 봄): 얼굴 닮음 · 유니폼 보임 · 의상 상징 · 표정·자세 · 화풍 → 하나라도 아니면 다시(1번만)."""
    import anthropic
    meter.check(3, "그림 점검(Claude Haiku)")
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip())
    msg = client.messages.create(              # 2026-11-25: 그림 보는 점검은 Groq 가 못 해서 가장 싼 Claude Haiku(예전 Opus)
        model=art.HAIKU, max_tokens=4000, output_config={"effort": "low"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(_small_jpeg(png)).decode()}},
            {"type": "text", "text": f"이 그림은 {pk['subject_en']}({pk['team_en']}, {pk['role']})의 판타지 포스터여야 한다. 시트: {json.dumps(w['sheet'], ensure_ascii=False)}\n"
                                     '각 항목 true/false 와 한 줄 이유를 JSON 으로: {"likeness":true,"kit":true,"costume":true,"emotion":true,"style":true,"wings":false,"text_in_image":false,"why":""}'}]}])
    u = msg.usage
    pin, pout = art.CLAUDE_PRICE[art.HAIKU]
    meter.add((u.input_tokens * pin + u.output_tokens * pout) / 1e6 * art._rate(), "그림 점검(Claude Haiku)")
    t = "".join(b.text for b in msg.content if b.type == "text")
    from . import safe
    try:
        res = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except ValueError:
        res = {}
    if safe.v_check(res):                      # 점검 답 형식이 틀리면 첫 그림 그대로(점검 못 함 표시) — 이 기사를 멈추지 않음
        return {"ok": True, "likeness": True, "why": "그림 점검 답 형식 틀림 → 점검 못 함(첫 그림 그대로)"}
    wings_ok = str((w.get("sheet") or {}).get("rank", "")).startswith("신화")
    res["ok"] = all(res.get(k) for k in ("likeness", "kit", "costume", "emotion", "style")) and (wings_ok or not res.get("wings"))
    return res
