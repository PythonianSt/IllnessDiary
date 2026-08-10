import streamlit as st
import pandas as pd
import requests
import base64
import io
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="Illness Diary",
    page_icon="🌿",
    layout="centered"
)

BKK = ZoneInfo("Asia/Bangkok")

GITHUB_TOKEN = st.secrets["github"]["token"]
GITHUB_OWNER = st.secrets["github"]["owner"]
GITHUB_REPO = st.secrets["github"]["repo"]
GITHUB_BRANCH = st.secrets["github"].get("branch", "main")
CSV_PATH = st.secrets["github"].get(
    "csv_path",
    "data/illness_diary.csv"
)

USERS = dict(st.secrets["users"])

COLUMNS = [
    "timestamp_bkk",
    "nickname",
    "date",
    "time",
    "pain_status",
    "activity",
    "pain_location",
    "pain_score",
    "inner_thought",
    "management",
    "next_activity",
    "pain_reduction_technique"
]


# =========================================================
# STYLE
# =========================================================

st.markdown("""
<style>

.block-container {
    max-width: 850px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

.title-box {
    padding: 22px;
    border-radius: 18px;
    background: rgba(120,180,150,0.10);
    margin-bottom: 15px;
}

.small-note {
    opacity: 0.75;
    font-size: 0.90rem;
}

.user-box {
    padding: 12px 16px;
    border-radius: 14px;
    background: rgba(128,128,128,0.08);
    margin-bottom: 15px;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# GITHUB FUNCTIONS
# =========================================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def github_url():
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{CSV_PATH}"
    )


def empty_dataframe():
    return pd.DataFrame(columns=COLUMNS)


def read_csv_from_github():
    """
    Return:
        dataframe, sha
    """

    url = github_url()

    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=20
    )

    # ยังไม่มีไฟล์
    if response.status_code == 404:
        return empty_dataframe(), None

    response.raise_for_status()

    payload = response.json()

    sha = payload["sha"]

    encoded = payload["content"].replace("\n", "")
    decoded = base64.b64decode(encoded).decode("utf-8-sig")

    if not decoded.strip():
        return empty_dataframe(), sha

    df = pd.read_csv(
        io.StringIO(decoded),
        dtype=str,
        keep_default_na=False
    )

    # รองรับกรณีเพิ่ม column ในอนาคต
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[COLUMNS], sha


def write_csv_to_github(df, sha=None):
    """
    เขียน CSV ทั้งไฟล์กลับ GitHub
    """

    csv_text = df.to_csv(index=False)
    content_encoded = base64.b64encode(
        csv_text.encode("utf-8-sig")
    ).decode("utf-8")

    payload = {
        "message": "Update Illness Diary",
        "content": content_encoded,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        github_url(),
        headers=github_headers(),
        json=payload,
        timeout=20
    )

    if response.status_code not in [200, 201]:
        raise RuntimeError(
            f"GitHub error {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


def append_record_safely(record, max_retry=4):
    """
    GitHub Contents API ใช้การอ่าน SHA ปัจจุบันก่อนเขียน
    ถ้ามีคนอื่นบันทึกพร้อมกัน ให้ retry
    """

    for attempt in range(max_retry):

        df, sha = read_csv_from_github()

        new_row = pd.DataFrame([record])

        df_new = pd.concat(
            [df, new_row],
            ignore_index=True
        )

        try:
            write_csv_to_github(df_new, sha)
            return True

        except RuntimeError as e:

            # อาจเกิด SHA conflict
            if attempt < max_retry - 1:
                time.sleep(0.7)
                continue

            raise e

    return False


# =========================================================
# LOGIN
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "nickname" not in st.session_state:
    st.session_state.nickname = None


def logout():
    st.session_state.logged_in = False
    st.session_state.nickname = None
    st.rerun()


def login_page():

    st.markdown("""
    <div class="title-box">
        <h1>🌿 Illness Diary</h1>
        <p>
        บันทึกช่วงเวลาที่ปวดและไม่ปวด
        เพื่อเรียนรู้ว่าอะไรสัมพันธ์กับอาการ
        และอะไรช่วยให้เราใช้ชีวิตได้ดีขึ้น
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("🔐 เข้าสู่หน้าของฉัน")

    with st.form("login_form"):

        nickname = st.text_input(
            "ชื่อเล่น",
            placeholder="เช่น นัท"
        ).strip()

        pin = st.text_input(
            "รหัส",
            type="password",
            placeholder="••••"
        ).strip()

        login_button = st.form_submit_button(
            "เข้าสู่ระบบ",
            use_container_width=True
        )

    if login_button:

        if not nickname or not pin:
            st.warning("กรุณากรอกชื่อเล่นและรหัส")

        elif nickname not in USERS:
            st.error("ชื่อเล่นหรือรหัสไม่ถูกต้อง")

        elif str(USERS[nickname]) != pin:
            st.error("ชื่อเล่นหรือรหัสไม่ถูกต้อง")

        else:
            st.session_state.logged_in = True
            st.session_state.nickname = nickname
            st.rerun()

    st.markdown("""
    <div class="small-note">
    ข้อมูลในสมุดนี้ใช้เพื่อทบทวนรูปแบบของอาการ
    ไม่จำเป็นต้องจดทุกครั้ง หากการจดทำให้กังวลหรือ
    จดจ่อกับความปวดมากเกินไป สามารถหยุดพักได้
    </div>
    """, unsafe_allow_html=True)


# =========================================================
# MAIN APP
# =========================================================

if not st.session_state.logged_in:
    login_page()
    st.stop()


nickname = st.session_state.nickname

st.markdown(
    f"""
    <div class="user-box">
        👤 หน้าของ <b>{nickname}</b>
    </div>
    """,
    unsafe_allow_html=True
)

top1, top2 = st.columns([4, 1])

with top1:
    st.title("🌿 Illness Diary")

with top2:
    if st.button("ออกจากระบบ"):
        logout()


tab1, tab2 = st.tabs([
    "✍️ บันทึกวันนี้",
    "📖 บันทึกของฉัน"
])


# =========================================================
# TAB 1 : NEW ENTRY
# =========================================================

with tab1:

    st.subheader("บันทึกช่วงหนึ่งของวันนี้")

    now_bkk = datetime.now(BKK)

    with st.form(
        "diary_form",
        clear_on_submit=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            diary_date = st.date_input(
                "📅 วัน",
                value=now_bkk.date(),
                format="DD/MM/YYYY"
            )

        with col2:
            diary_time = st.time_input(
                "🕒 เวลา",
                value=now_bkk.time().replace(
                    second=0,
                    microsecond=0
                ),
                step=300
            )

        st.markdown("### ตอนนั้นเป็นอย่างไร")

        pain_status = st.radio(
            "ตอนนั้น",
            ["ปวด", "ไม่ปวด"],
            horizontal=True
        )

        activity = st.text_area(
            "ตอนปวด/ไม่ปวด กำลังทำอะไร",
            placeholder=(
                "เช่น นั่งเรียน เดิน เล่นกีฬา "
                "นอนพัก ทำงานหน้าคอมพิวเตอร์"
            )
        )

        pain_location = ""
        pain_score = ""

        if pain_status == "ปวด":

            pain_location = st.text_input(
                "📍 ปวดตรงไหนของร่างกาย",
                placeholder=(
                    "เช่น หลังล่างขวา "
                    "คอและสะบักซ้าย"
                )
            )

            pain_score = st.slider(
                "คะแนนปวด",
                min_value=0,
                max_value=10,
                value=5
            )

        else:
            st.success(
                "ช่วงที่ไม่ปวดก็สำคัญมาก "
                "เพราะช่วยให้เราเห็นว่าอะไรทำให้อาการดีขึ้น"
            )

        inner_thought = st.text_area(
            "💭 ตอนนั้นเกิดความคิดในใจอะไร",
            placeholder=(
                "เช่น กลัวว่าจะปวดมากขึ้น / "
                "วันนี้รู้สึกว่าร่างกายดีขึ้น / "
                "ไม่ได้คิดถึงเรื่องปวดเลย"
            )
        )

        management = st.text_area(
            "🧭 จัดการอย่างไร",
            placeholder=(
                "เช่น พัก เปลี่ยนท่า เดิน "
                "หายใจช้า ๆ กดจุด รับประทานยา"
            )
        )

        next_activity = st.text_area(
            "🚶 แล้วทำอะไรต่อ",
            placeholder=(
                "เช่น กลับไปเรียนต่อ "
                "เดินต่อได้ กลับห้องพัก "
                "เล่นกีฬาต่อแต่ลดความหนัก"
            )
        )

        pain_reduction_technique = st.text_area(
            "🌱 มีเทคนิคลดปวดอะไรที่ช่วย",
            placeholder=(
                "เช่น diaphragmatic breathing, "
                "acupressure, stretching, "
                "ประคบ, Kinesio tape หรืออื่น ๆ"
            )
        )

        submitted = st.form_submit_button(
            "💾 บันทึก",
            type="primary",
            use_container_width=True
        )

    if submitted:

        if not activity.strip():
            st.warning(
                "กรุณาระบุว่าขณะนั้นกำลังทำอะไร"
            )

        elif (
            pain_status == "ปวด"
            and not pain_location.strip()
        ):
            st.warning(
                "กรุณาระบุตำแหน่งที่ปวด"
            )

        else:

            timestamp_bkk = datetime.now(BKK)

            record = {
                "timestamp_bkk":
                    timestamp_bkk.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),

                "nickname":
                    nickname,

                "date":
                    diary_date.strftime(
                        "%Y-%m-%d"
                    ),

                "time":
                    diary_time.strftime(
                        "%H:%M"
                    ),

                "pain_status":
                    pain_status,

                "activity":
                    activity.strip(),

                "pain_location":
                    pain_location.strip()
                    if pain_status == "ปวด"
                    else "",

                "pain_score":
                    str(pain_score)
                    if pain_status == "ปวด"
                    else "",

                "inner_thought":
                    inner_thought.strip(),

                "management":
                    management.strip(),

                "next_activity":
                    next_activity.strip(),

                "pain_reduction_technique":
                    pain_reduction_technique.strip()
            }

            try:

                with st.spinner(
                    "กำลังบันทึก..."
                ):
                    append_record_safely(
                        record
                    )

                st.success(
                    "✅ บันทึกเรียบร้อยแล้ว"
                )

                st.balloons()

            except Exception as e:

                st.error(
                    "บันทึกข้อมูลไม่สำเร็จ"
                )

                with st.expander(
                    "รายละเอียดสำหรับผู้ดูแลระบบ"
                ):
                    st.code(str(e))


# =========================================================
# TAB 2 : PERSONAL HISTORY
# =========================================================

with tab2:

    st.subheader(
        f"📖 บันทึกของ {nickname}"
    )

    try:

        df, _ = read_csv_from_github()

        if df.empty:

            st.info(
                "ยังไม่มีข้อมูลบันทึก"
            )

        else:

            personal = df[
                df["nickname"] == nickname
            ].copy()

            if personal.empty:

                st.info(
                    "ยังไม่มีข้อมูลบันทึกของคุณ"
                )

            else:

                personal["datetime_sort"] = (
                    personal["date"]
                    + " "
                    + personal["time"]
                )

                personal = personal.sort_values(
                    "datetime_sort",
                    ascending=False
                )

                total_entries = len(personal)

                pain_entries = (
                    personal["pain_status"]
                    == "ปวด"
                ).sum()

                no_pain_entries = (
                    personal["pain_status"]
                    == "ไม่ปวด"
                ).sum()

                c1, c2, c3 = st.columns(3)

                c1.metric(
                    "บันทึกทั้งหมด",
                    total_entries
                )

                c2.metric(
                    "ช่วงที่ปวด",
                    pain_entries
                )

                c3.metric(
                    "ช่วงที่ไม่ปวด",
                    no_pain_entries
                )

                st.divider()

                display_df = personal[
                    [
                        "date",
                        "time",
                        "pain_status",
                        "activity",
                        "pain_location",
                        "pain_score",
                        "inner_thought",
                        "management",
                        "next_activity",
                        "pain_reduction_technique"
                    ]
                ].rename(
                    columns={
                        "date": "วัน",
                        "time": "เวลา",
                        "pain_status": "ปวด/ไม่ปวด",
                        "activity": "กำลังทำอะไร",
                        "pain_location": "ตำแหน่งปวด",
                        "pain_score": "คะแนนปวด",
                        "inner_thought": "ความคิดในใจ",
                        "management": "จัดการอย่างไร",
                        "next_activity": "ทำอะไรต่อ",
                        "pain_reduction_technique":
                            "เทคนิคลดปวด"
                    }
                )

                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )

                st.divider()

                st.subheader(
                    "🌱 ช่วงที่ไม่ปวด"
                )

                no_pain = personal[
                    personal["pain_status"]
                    == "ไม่ปวด"
                ]

                if no_pain.empty:

                    st.caption(
                        "ยังไม่มีบันทึกช่วงที่ไม่ปวด"
                    )

                else:

                    for _, row in no_pain.head(
                        10
                    ).iterrows():

                        with st.expander(
                            f"🌿 {row['date']} "
                            f"{row['time']} — "
                            f"{row['activity']}"
                        ):

                            if row[
                                "inner_thought"
                            ]:
                                st.write(
                                    "**ตอนนั้นคิด/รู้สึก:**",
                                    row[
                                        "inner_thought"
                                    ]
                                )

                            if row[
                                "pain_reduction_technique"
                            ]:
                                st.write(
                                    "**สิ่งที่ช่วย:**",
                                    row[
                                        "pain_reduction_technique"
                                    ]
                                )

                            if row[
                                "next_activity"
                            ]:
                                st.write(
                                    "**จากนั้นทำต่อ:**",
                                    row[
                                        "next_activity"
                                    ]
                                )

    except Exception as e:

        st.error(
            "อ่านข้อมูลจาก GitHub ไม่สำเร็จ"
        )

        with st.expander(
            "รายละเอียดสำหรับผู้ดูแลระบบ"
        ):
            st.code(str(e))


st.divider()

st.caption(
    "Illness Diary • "
    "เรียนรู้ทั้งช่วงที่ปวดและช่วงที่ใช้ชีวิตได้ดี"
)