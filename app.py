# app.py — Mood & Move (Supabase Multi-user · Daily 1Q → Result/Recommend → Dashboard)
# - Step UI with progress & step indicator
# - Locks question & recommendation per day
# - Prevents duplicate point increment per day
# - 7/14/30-day dashboard period toggle
# - Supabase Python v2 compatible (no insert().select("*") chaining)
# - FIX: If user already answered today, show the SAME saved question in read-only (stored question_id)

import json
import datetime
import random
from pathlib import Path

import pandas as pd
import altair as alt
import streamlit as st
from supabase import create_client, Client

# ---------- App config ----------
st.set_page_config(page_title="Mood & Move", page_icon="✨", layout="centered")

# ---------- Data ----------
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
EMOTIONS = ["행복", "불안", "분노", "무기력", "슬픔", "집중"]
LEVEL_THRESHOLDS = [0, 3, 7, 15, 30, 60]

@st.cache_data
def load_data():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))

data = load_data()
emotions = [e for e in EMOTIONS if e in data] or list(data.keys())

# ---------- Supabase ----------
def get_supabase() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        st.error("🚨 Streamlit secrets에 SUPABASE_URL / SUPABASE_ANON_KEY를 설정하세요.")
        st.stop()
    return create_client(url, key)

@st.cache_resource
def supabase_client():
    return get_supabase()

sb = supabase_client()

def upsert_user(sb: Client, username: str):
    res = sb.table("users").select("*").eq("username", username).execute()
    if res.data:
        return res.data[0]
    res = sb.table("users").insert({"username": username}).execute()
    return res.data[0]

def fetch_user_logs(sb: Client, user_id: str, days: int = 120) -> pd.DataFrame:
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    res = sb.table("logs").select("*").eq("user_id", user_id).gte("log_date", since).order("log_date").execute()
    return pd.DataFrame(res.data or [])

def get_today_row(sb: Client, user_id: str, day: str):
    res = sb.table("logs").select("*").eq("user_id", user_id).eq("log_date", day).limit(1).execute()
    return res.data[0] if res.data else None

def insert_today_row(sb: Client, user_id: str, day: str, payload: dict):
    payload = {"user_id": user_id, "log_date": day, **payload}
    res = sb.table("logs").insert(payload).execute()
    return res.data[0]

def update_row(sb: Client, row_id: int, payload: dict):
    sb.table("logs").update(payload).eq("id", row_id).execute()

# ---------- Questions (10 × 4 options) ----------
QUESTIONS = [
    {"id": "q1","text": "오늘 가장 듣고 싶은 음악은?",
     "options":[
        {"key":"kpop_dance","label":"신나는 K-POP 댄스곡","weights":{"행복":1.0,"집중":0.2}},
        {"key":"ballad","label":"센치한 발라드","weights":{"슬픔":1.0,"행복":-0.2}},
        {"key":"rock","label":"에너지 넘치는 락/브릿팝","weights":{"분노":1.0,"행복":0.2}},
        {"key":"lofi","label":"차분한 로파이 재즈","weights":{"집중":1.0,"불안":-0.2}}
     ]},
    {"id": "q2","text": "오늘 가장 보고 싶은 영화는?",
     "options":[
        {"key":"romcom","label":"달달한 로맨틱 코미디","weights":{"행복":1.0,"집중":0.2}},
        {"key":"drama","label":"감정선을 건드리는 드라마","weights":{"슬픔":1.0,"행복":-0.2}},
        {"key":"action","label":"몰입감 강한 액션 스릴러","weights":{"집중":0.8,"분노":0.6}},
        {"key":"docu","label":"차분한 다큐멘터리","weights":{"집중":1.0,"불안":-0.2}}
     ]},
    {"id": "q3","text": "오늘 읽고 싶은 책은?",
     "options":[
        {"key":"selfhelp","label":"동기부여 되는 자기계발서","weights":{"집중":1.0,"행복":0.4}},
        {"key":"novel","label":"감정에 몰입되는 장편 소설","weights":{"슬픔":0.8,"행복":-0.2}},
        {"key":"essay","label":"차분한 감성 에세이","weights":{"불안":0.5,"슬픔":0.6}},
        {"key":"comic","label":"가볍게 웃을 수 있는 만화","weights":{"행복":1.0,"무기력":-0.3}}
     ]},
    {"id": "q4","text": "오늘 여행을 간다면 어디로 가고 싶나요?",
     "options":[
        {"key":"beach","label":"햇살 가득한 해변","weights":{"행복":1.0,"집중":0.2}},
        {"key":"mountain","label":"조용한 산속 트레킹","weights":{"불안":0.8,"집중":0.5}},
        {"key":"city","label":"활기찬 도심 탐험","weights":{"행복":0.6,"분노":0.4}},
        {"key":"home","label":"집에서 여유롭게 쉬기","weights":{"무기력":1.0,"슬픔":0.4}}
     ]},
    {"id": "q5","text": "오늘 가장 만나고 싶은 친구는?",
     "options":[
        {"key":"cheerful","label":"항상 웃고 떠드는 친구","weights":{"행복":1.0,"집중":0.2}},
        {"key":"listener","label":"내 얘기를 잘 들어주는 친구","weights":{"슬픔":0.8,"행복":0.3}},
        {"key":"motivator","label":"도전심을 북돋아주는 친구","weights":{"집중":0.8,"행복":0.2}},
        {"key":"quiet","label":"그냥 옆에만 있어도 편한 친구","weights":{"불안":0.7,"무기력":0.5}}
     ]},
    {"id": "q6","text": "오늘 걷고 싶은 동네는?",
     "options":[
        {"key":"park","label":"잔디와 벤치가 있는 공원","weights":{"행복":0.8,"불안":0.3}},
        {"key":"river","label":"물소리 들리는 강변 산책로","weights":{"슬픔":0.7,"집중":0.4}},
        {"key":"alley","label":"작은 카페가 있는 골목길","weights":{"집중":0.8,"행복":0.4}},
        {"key":"home","label":"집 주변 단순 산책","weights":{"무기력":1.0,"불안":0.4}}
     ]},
    {"id": "q7","text": "지금 타고 싶은 대중교통은?",
     "options":[
        {"key":"bus","label":"창밖을 보며 여유 있게 가는 버스","weights":{"불안":0.5,"슬픔":0.5}},
        {"key":"subway","label":"빠르고 효율적인 지하철","weights":{"집중":1.0,"행복":0.3}},
        {"key":"bike","label":"시원한 바람을 가르는 자전거","weights":{"행복":0.8,"분노":0.4}},
        {"key":"walk","label":"느긋하게 걷기","weights":{"무기력":0.6,"슬픔":0.4}}
     ]},
    {"id": "q8","text": "오늘 먹고 싶은 음식은?",
     "options":[
        {"key":"spicy","label":"매운 음식으로 스트레스 해소","weights":{"분노":1.0,"행복":0.2}},
        {"key":"sweet","label":"달달한 디저트로 기분전환","weights":{"행복":1.0,"무기력":-0.3}},
        {"key":"healthy","label":"건강한 샐러드/웰빙식","weights":{"집중":0.8,"불안":0.3}},
        {"key":"comfort","label":"집밥 같은 편안한 음식","weights":{"무기력":0.8,"슬픔":0.4}}
     ]},
    {"id": "q9","text": "지금 당장 하고 싶은 활동은?",
     "options":[
        {"key":"exercise","label":"땀나는 운동으로 리프레시","weights":{"행복":0.9,"집중":0.6}},
        {"key":"sleep","label":"아무것도 안 하고 잠자기","weights":{"무기력":1.0,"슬픔":0.4}},
        {"key":"study","label":"집중해서 공부/업무하기","weights":{"집중":1.0,"불안":0.4}},
        {"key":"chat","label":"친구와 수다 떨기","weights":{"행복":1.0,"분노":-0.2}}
     ]},
    {"id": "q10","text": "지금 가장 필요한 건?",
     "options":[
        {"key":"hug","label":"누군가의 포근한 포옹","weights":{"슬픔":0.9,"행복":0.5}},
        {"key":"focus","label":"조용하고 집중할 수 있는 공간","weights":{"집중":1.0,"불안":0.4}},
        {"key":"fun","label":"유쾌한 웃음과 에너지","weights":{"행복":1.0,"집중":0.3}},
        {"key":"break","label":"아무도 건드리지 않는 혼자만의 휴식","weights":{"무기력":1.0,"불안":0.5}}
     ]}
]

def infer_emotion_from_choice(choice):
    scores = {e: 0.0 for e in emotions}
    for emo, w in choice["weights"].items():
        if emo in scores:
            scores[emo] += w
    max_val = max(scores.values()) if scores else 0
    cands = [e for e, v in scores.items() if abs(v - max_val) < 1e-9]
    return random.choice(cands) if cands else emotions[0], scores

# ---------- History / cooldown helpers ----------
def build_history_from_df(df: pd.DataFrame):
    hist = {}
    if df.empty:
        return hist
    for col in ["quote_id", "challenge_id"]:
        sub = df.dropna(subset=[col, "log_date"])
        for _, r in sub.iterrows():
            item_id = r[col]
            try:
                dt = datetime.datetime.fromisoformat(str(r["log_date"]))
            except Exception:
                dt = datetime.datetime.strptime(str(r["log_date"]), "%Y-%m-%d")
            latest = hist.get(item_id)
            if (latest is None) or (dt > latest):
                hist[item_id] = dt
    return hist

def eligible(items, history, today):
    ok = []
    for it in items:
        iid = it["id"]
        cooldown = int(it.get("cooldown_days", 0))
        last = history.get(iid)
        if (last is None) or ((today - last).days >= cooldown):
            ok.append(it)
    ok.sort(key=lambda x: x.get("difficulty", 1))
    return ok

def pick_item(items, history, today):
    pool = eligible(items, history, today)
    if not pool:
        items_sorted = sorted(items, key=lambda x: history.get(x["id"], datetime.datetime(1970,1,1)))
        return items_sorted[0]
    first_diff = pool[0].get("difficulty", 1)
    tier = [x for x in pool if x.get("difficulty", 1) == first_diff]
    return random.choice(tier)

# ---------- Level helpers ----------
def calc_level(points: int) -> int:
    lvl = 0
    for i, th in enumerate(LEVEL_THRESHOLDS):
        if points >= th:
            lvl = i
    return max(1, lvl)

def progress_fraction(points: int) -> float:
    curr_idx = 0
    for i, th in enumerate(LEVEL_THRESHOLDS):
        if points >= th:
            curr_idx = i
    curr_th = LEVEL_THRESHOLDS[curr_idx]
    if curr_idx == len(LEVEL_THRESHOLDS) - 1:
        return 1.0
    next_th = LEVEL_THRESHOLDS[curr_idx + 1]
    span = max(1, next_th - curr_th)
    return max(0.0, min(1.0, (points - curr_th) / span))

# ---------- Sidebar: login ----------
st.sidebar.subheader("로그인")
username = st.sidebar.text_input("닉네임(간단히):", value=st.session_state.get("username", ""))
if st.sidebar.button("확인") or (username and "user" not in st.session_state):
    user = upsert_user(sb, username.strip())
    st.session_state["username"] = username.strip()
    st.session_state["user"] = user

if "user" not in st.session_state:
    st.info("왼쪽 사이드바에서 닉네임을 입력해 로그인해 주세요.")
    st.stop()

user = st.session_state["user"]
user_id = user["id"]

# ---------- Step Indicator Helpers ----------
STEPS = ["quiz", "result", "dashboard"]
STEP_TITLES = {"quiz": "① 문항", "result": "② 결과/추천", "dashboard": "③ 대시보드"}

def current_step_idx() -> int:
    step = st.session_state.get("step", "quiz")
    return STEPS.index(step) if step in STEPS else 0

def render_step_header():
    idx = current_step_idx()
    st.progress((idx + 1) / len(STEPS))
    cols = st.columns(len(STEPS))
    for i, key in enumerate(STEPS):
        label = STEP_TITLES[key]
        if i == idx:
            cols[i].markdown(f"**{label} · {i+1}/{len(STEPS)}**")
        else:
            cols[i].markdown(f"{label}")

# ---------- Header ----------
st.title("Mood & Move")
st.caption("하루 한 문항으로 감정을 추정하고, 맞춤 한 문장과 작은 행동을 추천합니다.")

# ---------- Dashboard Period Toggle (sidebar) ----------
PERIOD_OPTIONS = {"7일": 7, "14일": 14, "30일": 30}
st.sidebar.markdown("---")
st.sidebar.subheader("대시보드 기간")
period_label = st.sidebar.radio("기간 선택", list(PERIOD_OPTIONS.keys()), index=0, horizontal=True, key="period_radio")
DASHBOARD_DAYS = PERIOD_OPTIONS[period_label]

# ---------- Common state ----------
today_str = datetime.date.today().isoformat()
df_user_full = fetch_user_logs(sb, user_id, days=120)
history = build_history_from_df(df_user_full)

def get_or_create_today_row():
    row = get_today_row(sb, user_id, today_str)
    if row:
        return row
    # lock today's question in session
    if ("quiz_date" not in st.session_state) or (st.session_state["quiz_date"] != today_str):
        st.session_state["quiz_date"] = today_str
        q = random.choice(QUESTIONS)
        order = list(range(len(q["options"])))
        random.shuffle(order)
        st.session_state["quiz_qid"] = q["id"]
        st.session_state["quiz_order"] = order
        st.session_state["quiz_choice_index"] = None
    qid = st.session_state["quiz_qid"]
    q = next(x for x in QUESTIONS if x["id"] == qid)
    order = st.session_state["quiz_order"]
    options = [q["options"][i] for i in order]
    if st.session_state.get("quiz_choice_index") is None:
        return None
    choice = options[st.session_state["quiz_choice_index"]]
    emo, _ = infer_emotion_from_choice(choice)
    now = datetime.datetime.now()
    emo_data = data[emo]
    quote_item = pick_item(emo_data["quotes"], history, now)
    chall_item = pick_item(emo_data["challenges"], history, now)
    row = insert_today_row(
        sb, user_id, today_str,
        {
            "emotion": emo,
            "choice_key": choice["key"],
            "question_id": q["id"],          # ← 저장된 질문 ID
            "quote_id": quote_item["id"],
            "challenge_id": chall_item["id"],
            "completed": False,
            "points_delta": 0
        }
    )
    return row

# init step
if "step" not in st.session_state:
    st.session_state["step"] = "result" if get_today_row(sb, user_id, today_str) else "quiz"

# ---------- STEP 1: QUIZ ----------
if st.session_state["step"] == "quiz":
    render_step_header()

    # 이미 오늘 응답이 존재하면: 저장된 질문을 읽기 전용으로 보여주기
    today_row_existing = get_today_row(sb, user_id, today_str)
    if today_row_existing:
        st.header("① 오늘의 한 문항 (이미 제출됨)")
        qid_saved = today_row_existing.get("question_id")
        choice_saved = today_row_existing.get("choice_key")

        q = next((x for x in QUESTIONS if x["id"] == qid_saved), None) if qid_saved else None
        if not q:
            st.info("오늘 문항은 이미 제출되었습니다.")
            st.button("결과로 →", type="primary",
                      on_click=lambda: st.session_state.update({"step": "result"}),
                      key="btn_go_result_readonly")
            st.stop()

        st.write(f"**{q['text']}**")
        labels = [opt["label"] for opt in q["options"]]
        sel_index = next((i for i, opt in enumerate(q["options"]) if opt["key"] == choice_saved), 0)
        st.radio("선택", labels, index=sel_index, disabled=True, key="oneq_radio_readonly")

        col1, col2 = st.columns(2)
        with col1:
            st.button("결과로 →", type="primary",
                      on_click=lambda: st.session_state.update({"step": "result"}),
                      key="btn_go_result_from_readonly")
        with col2:
            st.button("대시보드로 →",
                      on_click=lambda: st.session_state.update({"step": "dashboard"}),
                      key="btn_go_dashboard_from_readonly")
        st.stop()

    # (아직 응답 전) 오늘 질문 고정/복원
    if ("quiz_date" not in st.session_state) or (st.session_state["quiz_date"] != today_str):
        st.session_state["quiz_date"] = today_str
        q = random.choice(QUESTIONS)
        order = list(range(len(q["options"])))
        random.shuffle(order)
        st.session_state["quiz_qid"] = q["id"]
        st.session_state["quiz_order"] = order
        st.session_state["quiz_choice_index"] = None

    qid = st.session_state["quiz_qid"]
    q = next(x for x in QUESTIONS if x["id"] == qid)
    order = st.session_state["quiz_order"]

    st.header("① 오늘의 한 문항")
    st.write(f"**{q['text']}**")

    options = [q["options"][i] for i in order]
    labels = [opt["label"] for opt in options]
    sel = st.radio(
        "하나를 선택하세요",
        labels,
        index=st.session_state.get("quiz_choice_index", None),
        key="oneq_radio"
    )
    if sel is not None:
        st.session_state["quiz_choice_index"] = labels.index(sel)

    col1, col2 = st.columns(2)
    with col1:
        disabled_next = st.session_state.get("quiz_choice_index") is None
        if st.button("결과 보기 →", type="primary", disabled=disabled_next, key="btn_go_result"):
            row = get_or_create_today_row()
            if row:
                st.session_state["step"] = "result"
                st.rerun()
    with col2:
        st.button("초기화", on_click=lambda: st.session_state.update({"quiz_choice_index": None}), key="btn_reset_quiz")

# ---------- STEP 2: RESULT + RECOMMEND ----------
elif st.session_state["step"] == "result":
    render_step_header()
    today_row = get_today_row(sb, user_id, today_str)
    if not today_row:
        st.session_state["step"] = "quiz"
        st.rerun()

    emo = today_row["emotion"]
    st.header("② 오늘의 결과")
    st.success(f"오늘의 감정: **{emo}**")
    if today_row.get("choice_key"):
        st.caption(f"선택: {today_row['choice_key']}")

    emo_data = data[emo]
    quote_id = today_row.get("quote_id")
    chall_id = today_row.get("challenge_id")
    quote_item = next((x for x in emo_data["quotes"] if x["id"] == quote_id), None)
    chall_item = next((x for x in emo_data["challenges"] if x["id"] == chall_id), None)
    now = datetime.datetime.now()
    if not quote_item or not chall_item:
        quote_item = pick_item(emo_data["quotes"], history, now)
        chall_item = pick_item(emo_data["challenges"], history, now)
        update_row(sb, today_row["id"], {"quote_id": quote_item["id"], "challenge_id": chall_item["id"]})

    st.subheader(f"오늘의 추천 · {emo}")
    st.write(f"**한 문장**: {quote_item['text']}")
    st.write(f"**챌린지**: {chall_item['text']}")

    done = st.checkbox("챌린지 완료!", value=bool(today_row.get("completed")), key="chk_done")
    already_saved = bool(today_row.get("completed"))
    if already_saved:
        st.info("오늘 기록은 이미 저장되었습니다. (포인트는 하루 1회만 반영)")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("기록 저장", type="primary", disabled=already_saved, key="btn_save"):
            payload = {"completed": bool(done)}
            if done and not already_saved:
                payload["points_delta"] = 1
            update_row(sb, today_row["id"], payload)
            st.success("저장되었습니다.")
            st.balloons()
            st.session_state["step"] = "dashboard"
            st.rerun()
    with col2:
        st.button("← 문항 다시 보기", on_click=lambda: st.session_state.update({"step": "quiz"}), key="btn_back_quiz")
    with col3:
        st.button("대시보드로 →", on_click=lambda: st.session_state.update({"step": "dashboard"}), key="btn_go_dashboard")

# ---------- STEP 3: DASHBOARD ----------
elif st.session_state["step"] == "dashboard":
    render_step_header()
    st.header("③ 대시보드")

    # 개인
    st.subheader(f"내 {DASHBOARD_DAYS}일 대시보드")
    dfp = fetch_user_logs(sb, user_id, days=DASHBOARD_DAYS)
    if dfp.empty:
        st.info("아직 기록이 없어요.")
    else:
        emo_counts = dfp.groupby("emotion")["id"].count().reset_index(name="count")
        chart = alt.Chart(emo_counts).mark_bar().encode(
            x="emotion:N", y="count:Q", tooltip=["emotion", "count"]
        )
        st.altair_chart(chart, use_container_width=True)
        st.metric(f"챌린지 완료율({DASHBOARD_DAYS}일)", f"{(dfp['completed'].mean()*100):.0f}%")

        st.write("최근 일별 감정")
        daily = (dfp.sort_values("log_date")
                    .groupby("log_date")
                    .agg({"emotion": "last"})
                    .reset_index())
        st.dataframe(daily, use_container_width=True)

    st.markdown("---")
    # 전체
    st.subheader(f"전체 {DASHBOARD_DAYS}일 감정 분포(익명 합산)")
    since = (datetime.date.today() - datetime.timedelta(days=DASHBOARD_DAYS)).isoformat()
    res = sb.table("logs").select("emotion, completed").gte("log_date", since).execute()
    all_df = pd.DataFrame(res.data or [])
    if all_df.empty:
        st.info("아직 전체 기록이 적습니다.")
    else:
        emo_counts = all_df.groupby("emotion")["emotion"].count().reset_index(name="count")
        chart = alt.Chart(emo_counts).mark_bar().encode(
            x="emotion:N", y="count:Q", tooltip=["emotion", "count"]
        )
        st.altair_chart(chart, use_container_width=True)
        st.metric(f"전체 평균 완료율({DASHBOARD_DAYS}일)", f"{(all_df['completed'].mean()*100):.0f}%")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.button("← 결과로 돌아가기", on_click=lambda: st.session_state.update({"step": "result"}), key="btn_back_result")
    with col2:
        st.button("오늘 문항 다시 보기", on_click=lambda: st.session_state.update({"step": "quiz"}), key="btn_go_quiz")

# ---------- Sidebar: Emotion Levels (last 120 days) ----------
df_user_levels = fetch_user_logs(sb, user_id, days=120)
points_by_emo = (df_user_levels.groupby("emotion")["points_delta"].sum() if not df_user_levels.empty else pd.Series(dtype=int))
st.sidebar.header("감정 레벨")
for e in emotions:
    pts = int(points_by_emo.get(e, 0))
    st.sidebar.write(f"{e} · Lv.{calc_level(pts)} · {pts} pts")
    st.sidebar.progress(progress_fraction(pts))
