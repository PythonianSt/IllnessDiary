import streamlit as st
import pandas as pd
import requests
import base64
import io
import time
import hashlib
import hmac
import secrets
import re

from datetime import datetime
from zoneinfo import ZoneInfo


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Illness Diary",
    page_icon="🌿",
    layout="centered"
)

BKK = ZoneInfo("Asia/Bangkok")


# =========================================================
# GITHUB CONFIG FROM STREAMLIT SECRETS
# =========================================================

GITHUB_TOKEN = st.secrets["github"]["token"]
GITHUB_OWNER = st.secrets["github"]["owner"]
GITHUB_REPO = st.secrets["github"]["repo"]
GITHUB_BRANCH = st.secrets["github"].get("branch", "main")

DIARY_PATH = st.secrets["github"].get(
    "csv_path",
    "data/illness_diary.csv"
)

USERS_PATH = st.secrets["github"].get(
    "users_path",
    "data/users.csv"
)


# =========================================================
# COLUMN DEFINITIONS
# =========================================================

DIARY_COLUMNS = [
    "record_id",
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

USER_COLUMNS = [
    "nickname",
    "nickname_key",
    "pin_salt",
    "pin_hash",
    "created_at",
    "status"
]


# =========================================================
# SESSION STATE
# =========================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "nickname" not in st.session_state:
    st.session_state.nickname = ""

if "nickname_key" not in st.session_state:
    st.session_state.nickname_key = ""


# =========================================================
# CSS
# =========================================================

st.markdown(
    """
    <style>

    .block-container {
        max-width: 860px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    .hero {
        padding: 24px;
        border-radius: 20px;
        background: rgba(80, 160, 120, 0.10);
        margin-bottom: 18px;
    }

    .hero h1 {
        margin-bottom: 6px;
    }

    .person-box {
        padding: 14px 18px;
        border-radius: 16px;
        background: rgba(120, 120, 120, 0.08);
        margin-bottom: 15px;
    }

    .gentle-box {
        padding: 16px;
        border-radius: 16px;
        background: rgba(100, 150, 120, 0.08);
        margin-top: 10px;
        margin-bottom: 10px;
    }

    .small-note {
        opacity: 0.75;
        font-size: 0.90rem;
    }

    div[data-testid="stMetric"] {
        border: 1px solid rgba(120,120,120,0.15);
        padding: 12px;
        border-radius: 14px;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# =========================================================
# BASIC HELPERS
# =========================================================

def now_bkk():
    return datetime.now(BKK)


def normalize_nickname(name: str) -> str:
    """
    ใช้เปรียบเทียบชื่อเล่นโดยไม่สนใจ
    ช่องว่างต้นท้าย และตัวพิมพ์เล็ก/ใหญ่ภาษาอังกฤษ
    """
    return " ".join(str(name).strip().split()).casefold()


def safe_display_nickname(name: str) -> str:
    """
    Normalize spacing แต่เก็บรูปแบบชื่อที่ผู้ใช้ตั้งไว้
    """
    return " ".join(str(name).strip().split())


def make_record_id():
    """
    ID ไม่ซ้ำสำหรับแต่ละ diary record
    """
    stamp = now_bkk().strftime("%Y%m%d%H%M%S%f")
    random_part = secrets.token_hex(4)
    return f"{stamp}_{random_part}"


# =========================================================
# PIN SECURITY
# =========================================================

PBKDF2_ITERATIONS = 250_000


def create_pin_hash(pin: str):
    """
    สร้าง random salt และ PBKDF2-HMAC-SHA256
    """
    salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    )

    return salt.hex(), digest.hex()


def verify_pin(pin: str, salt_hex: str, saved_hash_hex: str) -> bool:

    try:
        salt = bytes.fromhex(salt_hex)

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS
        )

        return hmac.compare_digest(
            digest.hex(),
            saved_hash_hex
        )

    except Exception:
        return False


def valid_pin(pin: str) -> bool:
    """
    PIN 4-6 หลัก
    """
    return bool(re.fullmatch(r"\d{4,6}", pin))


# =========================================================
# GITHUB API
# =========================================================

def github_headers():

    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }


def github_file_url(path):

    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    )


def read_csv_from_github(path, columns):
    """
    Return
    ------
    dataframe, sha
    """

    response = requests.get(
        github_file_url(path),
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=20
    )

    # ไฟล์ยังไม่เคยถูกสร้าง
    if response.status_code == 404:
        return pd.DataFrame(columns=columns), None

    response.raise_for_status()

    payload = response.json()

    sha = payload.get("sha")

    encoded = payload.get(
        "content",
        ""
    ).replace("\n", "")

    if not encoded:
        return pd.DataFrame(columns=columns), sha

    decoded = base64.b64decode(
        encoded
    ).decode(
        "utf-8-sig",
        errors="replace"
    )

    if not decoded.strip():
        return pd.DataFrame(columns=columns), sha

    df = pd.read_csv(
        io.StringIO(decoded),
        dtype=str,
        keep_default_na=False
    )

    # ถ้าในอนาคตเพิ่ม column
    for col in columns:
        if col not in df.columns:
            df[col] = ""

    return df[columns].copy(), sha


def write_csv_to_github(
    path,
    df,
    sha=None,
    commit_message="Update CSV"
):

    csv_text = df.to_csv(
        index=False,
        lineterminator="\n"
    )

    encoded = base64.b64encode(
        csv_text.encode("utf-8-sig")
    ).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": encoded,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        github_file_url(path),
        headers=github_headers(),
        json=payload,
        timeout=30
    )

    if response.status_code not in [200, 201]:

        raise RuntimeError(
            f"GitHub HTTP {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


# =========================================================
# USER DATABASE
# =========================================================

def read_users():

    return read_csv_from_github(
        USERS_PATH,
        USER_COLUMNS
    )


def register_user(
    nickname,
    pin,
    max_retry=5
):

    nickname = safe_display_nickname(
        nickname
    )

    nickname_key = normalize_nickname(
        nickname
    )

    for attempt in range(max_retry):

        users, sha = read_users()

        if not users.empty:

            existing = (
                users["nickname_key"]
                .astype(str)
                .map(normalize_nickname)
            )

            if nickname_key in existing.values:

                return (
                    False,
                    "ชื่อเล่นนี้มีผู้ใช้แล้ว กรุณาเลือกชื่ออื่น"
                )

        salt_hex, pin_hash_hex = (
            create_pin_hash(pin)
        )

        new_user = {
            "nickname": nickname,
            "nickname_key": nickname_key,
            "pin_salt": salt_hex,
            "pin_hash": pin_hash_hex,
            "created_at":
                now_bkk().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            "status": "active"
        }

        users_new = pd.concat(
            [
                users,
                pd.DataFrame([new_user])
            ],
            ignore_index=True
        )

        try:

            write_csv_to_github(
                USERS_PATH,
                users_new,
                sha,
                "Register Illness Diary user"
            )

            return (
                True,
                "สร้างบัญชีสำเร็จ"
            )

        except RuntimeError:

            # อาจมีผู้สมัครพร้อมกัน
            if attempt < max_retry - 1:
                time.sleep(
                    0.5 + attempt * 0.3
                )
                continue

            raise

    return (
        False,
        "ไม่สามารถสร้างบัญชีได้"
    )


def authenticate_user(
    nickname,
    pin
):

    nickname_key = normalize_nickname(
        nickname
    )

    users, _ = read_users()

    if users.empty:
        return None

    users["nickname_key"] = (
        users["nickname_key"]
        .astype(str)
        .map(normalize_nickname)
    )

    match = users[
        users["nickname_key"]
        == nickname_key
    ]

    if match.empty:
        return None

    row = match.iloc[0]

    if (
        str(row.get("status", "active"))
        .lower()
        != "active"
    ):
        return None

    if not verify_pin(
        pin,
        row["pin_salt"],
        row["pin_hash"]
    ):
        return None

    return {
        "nickname": row["nickname"],
        "nickname_key":
            row["nickname_key"]
    }


# =========================================================
# DIARY DATABASE
# =========================================================

def read_diary():

    return read_csv_from_github(
        DIARY_PATH,
        DIARY_COLUMNS
    )


def append_diary_record(
    record,
    max_retry=5
):

    for attempt in range(max_retry):

        df, sha = read_diary()

        new_df = pd.concat(
            [
                df,
                pd.DataFrame([record])
            ],
            ignore_index=True
        )

        try:

            write_csv_to_github(
                DIARY_PATH,
                new_df,
                sha,
                "Add Illness Diary record"
            )

            return True

        except RuntimeError:

            if attempt < max_retry - 1:

                time.sleep(
                    0.5 + attempt * 0.4
                )

                continue

            raise

    return False


# =========================================================
# LOGOUT
# =========================================================

def logout():

    st.session_state.logged_in = False
    st.session_state.nickname = ""
    st.session_state.nickname_key = ""

    st.rerun()


# =========================================================
# LANDING / LOGIN / REGISTER
# =========================================================

def login_register_page():

    st.markdown(
        """
        <div class="hero">
            <h1>🌿 Illness Diary</h1>
            <p>
            สมุดบันทึกเพื่อเรียนรู้ทั้งช่วงที่ปวด
            และช่วงที่ไม่ปวด สิ่งที่กำลังทำ
            ความคิดในขณะนั้น วิธีจัดการ
            และสิ่งที่ช่วยให้กลับไปทำกิจกรรมต่อได้
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    login_tab, register_tab = st.tabs(
        [
            "🔐 เข้าสู่ระบบ",
            "🆕 สร้างบัญชีครั้งแรก"
        ]
    )

    # -----------------------------------------------------
    # LOGIN
    # -----------------------------------------------------

    with login_tab:

        st.subheader(
            "เข้าสู่หน้าของฉัน"
        )

        with st.form(
            "login_form"
        ):

            nickname = st.text_input(
                "ชื่อเล่น",
                placeholder=(
                    "ชื่อเล่นที่ใช้ตอนสมัคร"
                )
            )

            pin = st.text_input(
                "รหัส PIN",
                type="password",
                placeholder="••••"
            )

            login_button = (
                st.form_submit_button(
                    "เข้าสู่ระบบ",
                    type="primary",
                    use_container_width=True
                )
            )

        if login_button:

            nickname = (
                safe_display_nickname(
                    nickname
                )
            )

            pin = pin.strip()

            if not nickname or not pin:

                st.warning(
                    "กรุณากรอกชื่อเล่นและรหัส"
                )

            else:

                try:

                    with st.spinner(
                        "กำลังตรวจสอบ..."
                    ):

                        user = (
                            authenticate_user(
                                nickname,
                                pin
                            )
                        )

                    if user is None:

                        st.error(
                            "ชื่อเล่นหรือรหัสไม่ถูกต้อง"
                        )

                    else:

                        st.session_state.logged_in = True

                        st.session_state.nickname = (
                            user["nickname"]
                        )

                        st.session_state.nickname_key = (
                            user["nickname_key"]
                        )

                        st.rerun()

                except Exception as e:

                    st.error(
                        "ไม่สามารถเข้าสู่ระบบได้"
                    )

                    with st.expander(
                        "รายละเอียดสำหรับผู้ดูแลระบบ"
                    ):
                        st.code(str(e))

    # -----------------------------------------------------
    # REGISTER
    # -----------------------------------------------------

    with register_tab:

        st.subheader(
            "สร้างบัญชีของฉัน"
        )

        st.info(
            "เลือกชื่อเล่นที่จำได้ง่าย "
            "และตั้งรหัสตัวเลข 4–6 หลัก"
        )

        with st.form(
            "register_form"
        ):

            new_nickname = st.text_input(
                "ชื่อเล่นที่ต้องการใช้",
                placeholder=(
                    "แนะนำให้หลีกเลี่ยงชื่อ-นามสกุลจริง"
                )
            )

            pin1 = st.text_input(
                "ตั้งรหัส PIN 4–6 หลัก",
                type="password",
                placeholder="••••"
            )

            pin2 = st.text_input(
                "ยืนยันรหัส PIN",
                type="password",
                placeholder="••••"
            )

            accept = st.checkbox(
                "ฉันจะจดจำชื่อเล่นและรหัสนี้ไว้"
            )

            register_button = (
                st.form_submit_button(
                    "สร้างบัญชี",
                    type="primary",
                    use_container_width=True
                )
            )

        if register_button:

            nickname = (
                safe_display_nickname(
                    new_nickname
                )
            )

            pin1 = pin1.strip()
            pin2 = pin2.strip()

            if not nickname:

                st.warning(
                    "กรุณาตั้งชื่อเล่น"
                )

            elif len(nickname) > 30:

                st.warning(
                    "ชื่อเล่นยาวเกินไป"
                )

            elif not valid_pin(pin1):

                st.warning(
                    "PIN ต้องเป็นตัวเลข 4–6 หลัก"
                )

            elif pin1 != pin2:

                st.warning(
                    "PIN ที่กรอกสองครั้งไม่ตรงกัน"
                )

            elif not accept:

                st.warning(
                    "กรุณายืนยันว่าจะจดจำชื่อเล่นและรหัส"
                )

            else:

                try:

                    with st.spinner(
                        "กำลังสร้างบัญชี..."
                    ):

                        ok, message = (
                            register_user(
                                nickname,
                                pin1
                            )
                        )

                    if ok:

                        st.success(
                            "✅ สร้างบัญชีสำเร็จ"
                        )

                        st.write(
                            f"ชื่อที่ใช้เข้าสู่ระบบ: "
                            f"**{nickname}**"
                        )

                        st.caption(
                            "ขณะนี้สามารถกลับไปที่ "
                            "แท็บ “เข้าสู่ระบบ” ได้เลย"
                        )

                    else:

                        st.error(
                            message
                        )

                except Exception as e:

                    st.error(
                        "สร้างบัญชีไม่สำเร็จ"
                    )

                    with st.expander(
                        "รายละเอียดสำหรับผู้ดูแลระบบ"
                    ):
                        st.code(str(e))

    st.divider()

    st.markdown(
        """
        <div class="small-note">
        Illness Diary มีไว้ช่วยให้เห็นรูปแบบของอาการ
        และสิ่งที่ช่วยให้ใช้ชีวิตได้ดีขึ้น
        ไม่จำเป็นต้องจดทุกครั้งที่รู้สึกปวด
        หากการบันทึกทำให้จดจ่อกับอาการมากเกินไป
        สามารถเว้นการบันทึกได้
        </div>
        """,
        unsafe_allow_html=True
    )


# =========================================================
# STOP HERE IF NOT LOGGED IN
# =========================================================

if not st.session_state.logged_in:

    login_register_page()

    st.stop()


# =========================================================
# USER PAGE
# =========================================================

nickname = st.session_state.nickname
nickname_key = st.session_state.nickname_key


st.markdown(
    f"""
    <div class="person-box">
        👤 หน้าของ <b>{nickname}</b>
    </div>
    """,
    unsafe_allow_html=True
)


head1, head2 = st.columns(
    [5, 1]
)

with head1:

    st.title(
        "🌿 Illness Diary"
    )

with head2:

    if st.button(
        "ออกจากระบบ",
        use_container_width=True
    ):

        logout()


tab_new, tab_history = st.tabs(
    [
        "✍️ บันทึก",
        "📖 บันทึกของฉัน"
    ]
)


# =========================================================
# TAB 1 — NEW ENTRY
# =========================================================

with tab_new:

    st.subheader(
        "บันทึกช่วงหนึ่งของวันนี้"
    )

    current = now_bkk()

    with st.form(
        "diary_form",
        clear_on_submit=True
    ):

        col_date, col_time = (
            st.columns(2)
        )

        with col_date:

            diary_date = (
                st.date_input(
                    "📅 วัน",
                    value=current.date(),
                    format="DD/MM/YYYY"
                )
            )

        with col_time:

            diary_time = (
                st.time_input(
                    "🕒 เวลา",
                    value=current.time().replace(
                        second=0,
                        microsecond=0
                    ),
                    step=300
                )
            )

        st.markdown(
            "### ตอนนั้นเป็นอย่างไร"
        )

        pain_status = st.radio(
            "ช่วงเวลานั้น",
            [
                "ปวด",
                "ไม่ปวด"
            ],
            horizontal=True
        )

        activity = st.text_area(
            "ตอนปวด/ไม่ปวด กำลังทำอะไร",
            placeholder=(
                "เช่น นั่งเรียน เดินไปเรียน "
                "เล่นกีฬา นอนพัก "
                "ทำงานหน้าคอมพิวเตอร์"
            ),
            height=90
        )

        pain_location = ""
        pain_score = ""

        if pain_status == "ปวด":

            st.markdown(
                "#### เกี่ยวกับความปวด"
            )

            pain_location = (
                st.text_input(
                    "📍 ปวดตรงไหนของร่างกาย",
                    placeholder=(
                        "เช่น หลังล่างขวา "
                        "คอและสะบักซ้าย"
                    )
                )
            )

            pain_score = st.slider(
                "คะแนนปวด 0–10",
                min_value=0,
                max_value=10,
                value=5,
                help=(
                    "0 = ไม่ปวด "
                    "และ 10 = ปวดมากที่สุด"
                )
            )

        else:

            st.markdown(
                """
                <div class="gentle-box">
                🌱 <b>ช่วงที่ไม่ปวดก็สำคัญ</b><br>
                การบันทึกช่วงที่สบายหรือใช้ชีวิต
                จนไม่ได้สนใจอาการ ช่วยให้เห็นว่า
                สถานการณ์หรือกิจกรรมอะไรสัมพันธ์
                กับช่วงที่ร่างกายทำงานได้ดี
                </div>
                """,
                unsafe_allow_html=True
            )

        inner_thought = (
            st.text_area(
                "💭 ตอนนั้นเกิดความคิดในใจอะไร",
                placeholder=(
                    "เช่น กลัวว่าจะปวดมากขึ้น / "
                    "วันนี้รู้สึกว่าร่างกายดีขึ้น / "
                    "ไม่ได้คิดถึงเรื่องปวดเลย"
                ),
                height=90
            )
        )

        management = (
            st.text_area(
                "🧭 จัดการอย่างไร",
                placeholder=(
                    "เช่น พัก เปลี่ยนท่า "
                    "ลุกเดิน หายใจช้า ๆ "
                    "กดจุด ประคบ หรือกินยา"
                ),
                height=90
            )
        )

        next_activity = (
            st.text_area(
                "🚶 แล้วทำอะไรต่อ",
                placeholder=(
                    "เช่น เรียนต่อ เดินต่อ "
                    "กลับห้อง เล่นกีฬาต่อ "
                    "แต่ลดความหนัก"
                ),
                height=90
            )
        )

        pain_reduction_technique = (
            st.text_area(
                "🌿 มีเทคนิคลดปวดอะไรที่ช่วย",
                placeholder=(
                    "เช่น diaphragmatic breathing, "
                    "acupressure, stretching, "
                    "ประคบ, Kinesio tape "
                    "หรือเทคนิคอื่น"
                ),
                height=90
            )
        )

        save_button = (
            st.form_submit_button(
                "💾 บันทึก",
                type="primary",
                use_container_width=True
            )
        )

    if save_button:

        activity = activity.strip()

        pain_location = (
            str(pain_location).strip()
        )

        inner_thought = (
            inner_thought.strip()
        )

        management = (
            management.strip()
        )

        next_activity = (
            next_activity.strip()
        )

        pain_reduction_technique = (
            pain_reduction_technique
            .strip()
        )

        if not activity:

            st.warning(
                "กรุณาระบุว่าตอนนั้นกำลังทำอะไร"
            )

        elif (
            pain_status == "ปวด"
            and not pain_location
        ):

            st.warning(
                "กรุณาระบุตำแหน่งที่ปวด"
            )

        else:

            record = {
                "record_id":
                    make_record_id(),

                "timestamp_bkk":
                    now_bkk().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),

                # เก็บ nickname สำหรับ display
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
                    activity,

                "pain_location":
                    (
                        pain_location
                        if pain_status
                        == "ปวด"
                        else ""
                    ),

                "pain_score":
                    (
                        str(pain_score)
                        if pain_status
                        == "ปวด"
                        else ""
                    ),

                "inner_thought":
                    inner_thought,

                "management":
                    management,

                "next_activity":
                    next_activity,

                "pain_reduction_technique":
                    pain_reduction_technique
            }

            try:

                with st.spinner(
                    "กำลังบันทึก..."
                ):

                    append_diary_record(
                        record
                    )

                st.success(
                    "✅ บันทึกเรียบร้อยแล้ว"
                )

                st.caption(
                    "ขอบคุณที่บันทึกทั้งสิ่งที่เกิดขึ้น "
                    "และสิ่งที่ช่วยให้ไปต่อได้"
                )

            except Exception as e:

                st.error(
                    "บันทึกข้อมูลไม่สำเร็จ"
                )

                with st.expander(
                    "รายละเอียดสำหรับผู้ดูแลระบบ"
                ):

                    st.code(str(e))


# =========================================================
# TAB 2 — USER HISTORY
# =========================================================

with tab_history:

    st.subheader(
        "📖 บันทึกของฉัน"
    )

    try:

        df, _ = read_diary()

        if df.empty:

            st.info(
                "ยังไม่มีข้อมูลบันทึก"
            )

        else:

            # เปรียบเทียบ nickname แบบ normalize
            # เพื่อไม่ให้ผู้ใช้อื่นเห็นข้อมูล
            df["_nickname_key"] = (
                df["nickname"]
                .astype(str)
                .map(normalize_nickname)
            )

            personal = df[
                df["_nickname_key"]
                == nickname_key
            ].copy()

            if personal.empty:

                st.info(
                    "ยังไม่มีข้อมูลบันทึกของคุณ"
                )

            else:

                personal[
                    "_sort"
                ] = (
                    personal["date"]
                    + " "
                    + personal["time"]
                )

                personal = (
                    personal.sort_values(
                        "_sort",
                        ascending=False
                    )
                )

                total_entries = len(
                    personal
                )

                pain_entries = int(
                    (
                        personal[
                            "pain_status"
                        ]
                        == "ปวด"
                    ).sum()
                )

                no_pain_entries = int(
                    (
                        personal[
                            "pain_status"
                        ]
                        == "ไม่ปวด"
                    ).sum()
                )

                pain_numeric = (
                    pd.to_numeric(
                        personal[
                            "pain_score"
                        ],
                        errors="coerce"
                    )
                )

                if (
                    pain_numeric
                    .notna()
                    .any()
                ):

                    avg_pain = round(
                        pain_numeric.mean(),
                        1
                    )

                else:

                    avg_pain = "-"

                c1, c2, c3, c4 = (
                    st.columns(4)
                )

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

                c4.metric(
                    "ปวดเฉลี่ย",
                    avg_pain
                )

                st.divider()

                # -----------------------------------------
                # Recent entries
                # -----------------------------------------

                st.markdown(
                    "### บันทึกล่าสุด"
                )

                for _, row in (
                    personal
                    .head(20)
                    .iterrows()
                ):

                    symbol = (
                        "🔴"
                        if row[
                            "pain_status"
                        ] == "ปวด"
                        else "🌿"
                    )

                    title = (
                        f"{symbol} "
                        f"{row['date']} "
                        f"{row['time']} — "
                        f"{row['activity']}"
                    )

                    with st.expander(
                        title
                    ):

                        st.write(
                            "**สถานะ:**",
                            row[
                                "pain_status"
                            ]
                        )

                        if (
                            row[
                                "pain_status"
                            ]
                            == "ปวด"
                        ):

                            st.write(
                                "**ตำแหน่ง:**",
                                row[
                                    "pain_location"
                                ]
                                or "-"
                            )

                            st.write(
                                "**คะแนนปวด:**",
                                row[
                                    "pain_score"
                                ]
                                or "-"
                            )

                        if row[
                            "inner_thought"
                        ]:

                            st.write(
                                "**ความคิดในใจ:**",
                                row[
                                    "inner_thought"
                                ]
                            )

                        if row[
                            "management"
                        ]:

                            st.write(
                                "**จัดการอย่างไร:**",
                                row[
                                    "management"
                                ]
                            )

                        if row[
                            "next_activity"
                        ]:

                            st.write(
                                "**แล้วทำอะไรต่อ:**",
                                row[
                                    "next_activity"
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

                st.divider()

                # -----------------------------------------
                # Pain-free / no pain periods
                # -----------------------------------------

                st.markdown(
                    "### 🌱 ช่วงที่ไม่ปวด"
                )

                no_pain = personal[
                    personal[
                        "pain_status"
                    ]
                    == "ไม่ปวด"
                ]

                if no_pain.empty:

                    st.caption(
                        "ยังไม่มีการบันทึกช่วงที่ไม่ปวด"
                    )

                else:

                    st.write(
                        "ลองสังเกตว่าช่วงเหล่านี้ "
                        "มีอะไรเหมือนกันบ้าง"
                    )

                    for _, row in (
                        no_pain
                        .head(10)
                        .iterrows()
                    ):

                        with st.expander(
                            f"🌿 "
                            f"{row['date']} "
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
                                "management"
                            ]:

                                st.write(
                                    "**สิ่งที่ทำ:**",
                                    row[
                                        "management"
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

                            if row[
                                "pain_reduction_technique"
                            ]:

                                st.write(
                                    "**สิ่งที่ช่วย:**",
                                    row[
                                        "pain_reduction_technique"
                                    ]
                                )

                st.divider()

                # -----------------------------------------
                # Full table
                # -----------------------------------------

                with st.expander(
                    "📋 ดูข้อมูลทั้งหมดของฉัน"
                ):

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
                            "date":
                                "วัน",
                            "time":
                                "เวลา",
                            "pain_status":
                                "ปวด/ไม่ปวด",
                            "activity":
                                "กำลังทำอะไร",
                            "pain_location":
                                "ตำแหน่งปวด",
                            "pain_score":
                                "คะแนนปวด",
                            "inner_thought":
                                "ความคิดในใจ",
                            "management":
                                "จัดการอย่างไร",
                            "next_activity":
                                "ทำอะไรต่อ",
                            "pain_reduction_technique":
                                "เทคนิคลดปวด"
                        }
                    )

                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True
                    )

    except Exception as e:

        st.error(
            "อ่านข้อมูลจาก GitHub ไม่สำเร็จ"
        )

        with st.expander(
            "รายละเอียดสำหรับผู้ดูแลระบบ"
        ):

            st.code(str(e))


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "🌿 Illness Diary • "
    "เรียนรู้ทั้งช่วงที่ปวด "
    "และช่วงที่ใช้ชีวิตได้ดี"
)
