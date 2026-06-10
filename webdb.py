"""
ParagonEdu Web - data layer
Reuses the desktop app's schema + logic patterns (same SHA-256 auth, same
tables) so a school's existing school_data.db works directly with the web app.
Phase 1: auth, school info, students, dashboard counts.
"""
import os, sqlite3, hashlib

# In production this points at the school's real DB. For Phase 1 dev we use a
# local file seeded with demo data if none exists.
DB_PATH = os.environ.get("PARAGON_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "school_data.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_pw(password):
    # SAME hashing as the desktop app -> existing accounts work unchanged
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate(username, password):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    conn.close()
    if not user:
        return None
    pw = (password or "")
    pwl = pw.lower()
    stored = user["password_hash"]
    if stored == _hash_pw(pw) or stored == _hash_pw(pwl):
        return dict(user)
    # alt password (first/last name fallback), case-insensitive
    try:
        alt = user["alt_password_hash"]
    except Exception:
        alt = ""
    if alt and (alt == _hash_pw(pw) or alt == _hash_pw(pwl)):
        return dict(user)
    return None


def get_school_info():
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM school_info WHERE id=1").fetchone()
        return dict(r) if r else {}
    finally:
        conn.close()


def get_students(active_only=True, class_level=None, search=None):
    conn = get_conn()
    q = "SELECT id, full_name, admission_no, gender, class_level, parent_phone FROM students"
    where = []
    params = []
    if active_only:
        where.append("(active=1 OR active IS NULL)")
    if class_level and class_level != "All":
        where.append("class_level=?"); params.append(class_level)
    if search:
        where.append("(full_name LIKE ? OR admission_no LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY class_level, full_name"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student(student_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    conn.close()
    return dict(r) if r else None


def get_all_class_names():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT class_level FROM students WHERE class_level IS NOT NULL AND class_level<>'' ORDER BY class_level").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def get_dashboard_counts():
    conn = get_conn()
    def count(sql):
        try:
            return conn.execute(sql).fetchone()[0]
        except Exception:
            return 0
    data = {
        "students": count("SELECT COUNT(*) FROM students WHERE (active=1 OR active IS NULL)"),
        "staff": count("SELECT COUNT(*) FROM staff"),
        "classes": len(get_all_class_names()),
        "subjects": count("SELECT COUNT(*) FROM subjects"),
    }
    conn.close()
    return data


# --- demo seed so Phase 1 runs even without a real DB ---
def ensure_demo_db():
    if os.path.exists(DB_PATH):
        return
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE school_info (id INTEGER PRIMARY KEY, name TEXT, session TEXT, term TEXT,
                                  max_ca1 INTEGER DEFAULT 20, max_ca2 INTEGER DEFAULT 20, max_exam INTEGER DEFAULT 60);
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, password_hash TEXT,
                            alt_password_hash TEXT, role TEXT, display_name TEXT, student_id INTEGER,
                            staff_id INTEGER, active INTEGER, must_change_pw INTEGER DEFAULT 0);
        CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, admission_no TEXT,
                               gender TEXT, class_level TEXT, parent_phone TEXT, parent_name TEXT,
                               date_of_birth TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE staff (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, staff_no TEXT, status TEXT);
        CREATE TABLE subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, sort_order INTEGER, included INTEGER DEFAULT 1);
        CREATE TABLE scores (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, subject_id INTEGER,
                             ca1 REAL, ca2 REAL, exam REAL);
        CREATE TABLE class_subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, class_name TEXT, subject_id INTEGER);
        CREATE TABLE fee_structures (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, class_level TEXT,
                                     session TEXT, term TEXT, amount REAL, category TEXT, description TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE fee_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, fee_id INTEGER,
                                   amount_paid REAL, payment_date TEXT, payment_method TEXT, receipt_no TEXT,
                                   session TEXT, term TEXT, recorded_by TEXT, note TEXT, payment_plan TEXT);
        CREATE TABLE fee_discounts (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, session TEXT,
                                    term TEXT, discount_type TEXT, amount REAL, reason TEXT);
    """)
    conn.execute("INSERT INTO school_info (id,name,session,term,max_ca1,max_ca2,max_exam) VALUES (1,'Paragon Demo Academy','2025/2026','3rd',20,20,60)")
    conn.execute("INSERT INTO users (username,password_hash,role,display_name,active) VALUES (?,?,?,?,1)",
                 ("admin", _hash_pw("admin123"), "admin", "Administrator"))
    demo = [("Adesola Muazz","PS/2025/001","M","Primary 1","08030000001"),
            ("Akanni Idris","PS/2025/002","M","Primary 1","08030000002"),
            ("Bello Samsudeen","PS/2025/003","M","Primary 2","08030000003"),
            ("Buhari Fatimoh","PS/2025/008","F","Primary 2","08030000004"),
            ("Oladejo Abudulsalam","PS/2025/004","M","Primary 3","08030000005")]
    for n,a,g,c,p in demo:
        conn.execute("INSERT INTO students (full_name,admission_no,gender,class_level,parent_phone,active) VALUES (?,?,?,?,?,1)",(n,a,g,c,p))
    for i,sn in enumerate(["English Language","Mathematics","Basic Science"],1):
        conn.execute("INSERT INTO subjects (name,sort_order,included) VALUES (?,?,1)",(sn,i))
    conn.execute("INSERT INTO staff (full_name,staff_no,status) VALUES ('Ibrahim Musa','STF/001','Active')")
    # a student login (Akanni Idris = student id 2): username=admission no, password=surname
    conn.execute("INSERT INTO users (username,password_hash,role,display_name,student_id,active) VALUES (?,?,?,?,?,1)",
                 ("PS/2025/002", _hash_pw("akanni"), "student", "Akanni Idris", 2))
    # sample scores for students 1,2,3 across the 3 subjects (subject ids 1,2,3)
    sample_scores = {
        1: [(18,17,52),(15,16,40),(19,18,55)],   # Adesola
        2: [(20,19,58),(17,18,50),(16,15,48)],   # Akanni
        3: [(12,14,35),(10,11,30),(14,13,38)],   # Bello
    }
    for sid, marks in sample_scores.items():
        for subj_id,(c1,c2,ex) in zip([1,2,3], marks):
            conn.execute("INSERT INTO scores (student_id,subject_id,ca1,ca2,exam) VALUES (?,?,?,?,?)",(sid,subj_id,c1,c2,ex))
    # --- demo fees: term fee per class for 3rd term ---
    fee_by_class = {"Primary 1":15000, "Primary 2":18000, "Primary 3":20000}
    for cls, amt in fee_by_class.items():
        conn.execute("INSERT INTO fee_structures (name,class_level,session,term,amount,category,active) VALUES (?,?,?,?,?,?,1)",
                     ("Tuition", cls, "2025/2026", "3rd", amt, "Tuition"))
    # sample payments (Adesola P1 paid 10000 of 15000; Akanni P1 paid full 15000; Bello P2 paid 0)
    conn.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (1,10000,'2026-01-15','Cash','RCT00001','2025/2026','3rd','admin')")
    conn.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (2,15000,'2026-01-20','Transfer','RCT00002','2025/2026','3rd','admin')")
    # sample MCQ questions (school + jamb) so CBT works on first run
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mcq_questions (id INTEGER PRIMARY KEY AUTOINCREMENT, exam_type TEXT, subject TEXT,
            question TEXT, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, answer TEXT, topic TEXT, year TEXT, active INTEGER DEFAULT 1);
    """)
    mcq = [
        ("school","Mathematics","What is 7 + 5?","10","11","12","13","C"),
        ("school","Mathematics","What is 9 x 3?","27","24","21","18","A"),
        ("school","Mathematics","Half of 50 is?","20","25","30","15","B"),
        ("school","English Language","Choose the correct plural of 'child'.","childs","childes","children","child","C"),
        ("school","English Language","A word that names a person is a?","verb","noun","adverb","adjective","B"),
        ("jamb","English Language","Choose the option nearest in meaning to 'rapid'.","slow","quick","late","heavy","B"),
        ("jamb","Mathematics","Simplify 2(3+4).","14","10","12","9","A"),
        ("jamb","Physics","The SI unit of force is?","Joule","Watt","Newton","Pascal","C"),
        ("jamb","Chemistry","The chemical symbol for water is?","CO2","H2O","O2","NaCl","B"),
    ]
    for et,subj,q,a,b,c,d,ans in mcq:
        conn.execute("INSERT INTO mcq_questions (exam_type,subject,question,option_a,option_b,option_c,option_d,answer,active) VALUES (?,?,?,?,?,?,?,?,1)",
                     (et,subj,q,a,b,c,d,ans))
    conn.commit(); conn.close()


# ============================================================
# PHASE 2 - Scores + Results
# ============================================================

def _grade_for(total, max_total=100):
    """Standard Nigerian grading. Scaled to max_total in case maxima differ."""
    pct = (total / max_total * 100) if max_total else 0
    if pct >= 75: return ("A", "Excellent")
    if pct >= 65: return ("B", "Very Good")
    if pct >= 55: return ("C", "Good")
    if pct >= 45: return ("D", "Pass")
    if pct >= 40: return ("E", "Weak Pass")
    return ("F", "Fail")


def get_class_subject_ids(class_name):
    """Subjects configured for a class (empty -> not configured)."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT subject_id FROM class_subjects WHERE class_name=?", (class_name,)).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_subjects_for_class(class_name):
    """Class subjects in get_subjects shape; falls back to all if unconfigured."""
    allsubs = get_subjects(included_only=True)
    ids = set(get_class_subject_ids(class_name))
    if not ids:
        return allsubs
    return [s for s in allsubs if s["id"] in ids]


def get_subjects(included_only=False):
    conn = get_conn()
    try:
        q = "SELECT * FROM subjects" + (" WHERE included=1" if included_only else "")
        try:
            q += " ORDER BY sort_order"
            rows = conn.execute(q).fetchall()
        except Exception:
            rows = conn.execute("SELECT * FROM subjects" + (" WHERE included=1" if included_only else "")).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_score(student_id, subject_id):
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM scores WHERE student_id=? AND subject_id=?", (student_id, subject_id)).fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        conn.close()


def save_score(student_id, subject_id, ca1, ca2, exam):
    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM scores WHERE student_id=? AND subject_id=?", (student_id, subject_id)).fetchone()
        if existing:
            conn.execute("UPDATE scores SET ca1=?, ca2=?, exam=? WHERE id=?", (ca1, ca2, exam, existing[0]))
        else:
            conn.execute("INSERT INTO scores (student_id, subject_id, ca1, ca2, exam) VALUES (?,?,?,?,?)",
                         (student_id, subject_id, ca1, ca2, exam))
        conn.commit()
        return True
    except Exception as e:
        return False
    finally:
        conn.close()


def get_student_subjects_for_scoring(student):
    """Subjects to score for a student, via their class config."""
    cls = student.get("class_level") or ""
    if cls:
        return get_subjects_for_class(cls)
    return get_subjects(included_only=True)


def _n(v):
    """Show whole numbers without .0 (97 not 97.0); blank stays blank."""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 1)
    except Exception:
        return v


def compute_student_result(student_id):
    """
    Build a full result for one student: each subject's CA1/CA2/Exam/Total/Grade,
    plus overall total, average, and grade. Read-only computation.
    """
    student = get_student(student_id)
    if not student:
        return None
    info = get_school_info()
    mca1 = int(info.get("max_ca1", 20) or 20)
    mca2 = int(info.get("max_ca2", 20) or 20)
    mexam = int(info.get("max_exam", 60) or 60)
    max_total = mca1 + mca2 + mexam

    subjects = get_student_subjects_for_scoring(student)
    rows = []
    grand_total = 0
    counted = 0
    for subj in subjects:
        sc = get_score(student_id, subj["id"]) or {}
        ca1 = sc.get("ca1"); ca2 = sc.get("ca2"); exam = sc.get("exam")
        has_any = any(v is not None and v != "" for v in (ca1, ca2, exam))
        total = (ca1 or 0) + (ca2 or 0) + (exam or 0)
        grade, remark = _grade_for(total, max_total)
        rows.append({
            "subject": subj["name"],
            "ca1": _n(ca1),
            "ca2": _n(ca2),
            "exam": _n(exam),
            "total": _n(total) if has_any else "",
            "grade": grade if has_any else "",
            "remark": remark if has_any else "",
        })
        if has_any:
            grand_total += total
            counted += 1
    average = round(grand_total / counted, 1) if counted else 0
    avg_grade, avg_remark = _grade_for(average, max_total)
    traits = get_student_traits(student_id)
    comments = get_student_comments(student_id)
    affective = [(t, traits.get(t), RATING_LABELS.get(traits.get(t), "")) for t in AFFECTIVE_TRAITS]
    psychomotor = [(t, traits.get(t), RATING_LABELS.get(traits.get(t), "")) for t in PSYCHOMOTOR_TRAITS]
    # auto comments as fallback when none saved
    auto_t, auto_h = auto_comments(average, max_total) if counted else ("", "")
    tcomment = comments.get("teacher_comment") or (auto_t if counted else "")
    hcomment = comments.get("head_comment") or (auto_h if counted else "")
    return {
        "student": student,
        "info": info,
        "maxima": {"ca1": mca1, "ca2": mca2, "exam": mexam, "total": max_total},
        "rows": rows,
        "grand_total": _n(grand_total),
        "subjects_counted": counted,
        "average": _n(average),
        "overall_grade": avg_grade if counted else "",
        "overall_remark": avg_remark if counted else "",
        "affective": affective,
        "psychomotor": psychomotor,
        "teacher_comment": tcomment,
        "head_comment": hcomment,
    }


# ============================================================
# PHASE 3 - Fees (overview + record payment), admin/bursar only
# ============================================================

def _norm_class(s):
    """Normalize class names for matching (K.G 1 == KG 1 == kg1)."""
    return (s or "").strip().lower().replace(".", "").replace("-", "").replace(" ", "")


def _current_session_term():
    info = get_school_info()
    return (info.get("session") or "").strip(), (info.get("term") or "").strip()


def get_fees_for_class(class_level, session=None, term=None):
    """Active fee_structures matching a class for the given session/term."""
    if session is None or term is None:
        session, term = _current_session_term()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM fee_structures WHERE (active=1 OR active IS NULL)"
        ).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    out = []
    nc = _norm_class(class_level)
    nt = (term or "").strip().lower()
    for r in rows:
        r = dict(r)
        if _norm_class(r.get("class_level")) != nc:
            continue
        # term match (trim/space tolerant); blank term on fee = applies to any
        ft = (r.get("term") or "").strip().lower()
        if ft and nt and ft != nt:
            continue
        out.append(r)
    return out


def get_student_discount(student_id, session=None, term=None):
    if session is None or term is None:
        session, term = _current_session_term()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT amount, term FROM fee_discounts WHERE student_id=?", (student_id,)).fetchall()
    except Exception:
        conn.close(); return 0.0
    conn.close()
    nt = (term or "").strip().lower()
    total = 0.0
    for r in rows:
        rt = (r["term"] or "").strip().lower()
        if rt and nt and rt != nt:
            continue
        total += (r["amount"] or 0)
    return total


def get_student_payments(student_id, session=None, term=None):
    if session is None or term is None:
        session, term = _current_session_term()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM fee_payments WHERE student_id=? ORDER BY payment_date DESC", (student_id,)
        ).fetchall()
    except Exception:
        conn.close(); return []
    conn.close()
    nt = (term or "").strip().lower()
    out = []
    for r in rows:
        r = dict(r)
        pt = (r.get("term") or "").strip().lower()
        if pt and nt and pt != nt:
            continue
        out.append(r)
    return out


def get_student_fee_summary(student_id):
    """due / paid / balance for the current term for one student."""
    student = get_student(student_id)
    if not student:
        return None
    session, term = _current_session_term()
    fees = get_fees_for_class(student.get("class_level"), session, term)
    due = sum((f.get("amount") or 0) for f in fees)
    discount = get_student_discount(student_id, session, term)
    payments = get_student_payments(student_id, session, term)
    paid = sum((p.get("amount_paid") or 0) for p in payments)
    net_due = max(due - discount, 0)
    balance = net_due - paid
    return {
        "student": student, "session": session, "term": term,
        "fees": fees, "due": due, "discount": discount, "net_due": net_due,
        "payments": payments, "paid": paid, "balance": balance,
    }


def get_fees_overview(class_level=None, search=None):
    """List students with due/paid/balance for the current term."""
    students = get_students(active_only=True, class_level=class_level, search=search)
    rows = []
    tot_due = tot_paid = tot_bal = 0.0
    for s in students:
        summ = get_student_fee_summary(s["id"])
        if not summ:
            continue
        rows.append({
            "id": s["id"], "full_name": s["full_name"], "admission_no": s.get("admission_no"),
            "class_level": s.get("class_level"),
            "due": summ["net_due"], "paid": summ["paid"], "balance": summ["balance"],
        })
        tot_due += summ["net_due"]; tot_paid += summ["paid"]; tot_bal += summ["balance"]
    return {"rows": rows, "tot_due": tot_due, "tot_paid": tot_paid, "tot_bal": tot_bal}


def record_payment(student_id, amount, method, date, note, recorded_by, fee_id=None):
    """Insert a fee_payment for the current session/term."""
    session, term = _current_session_term()
    conn = get_conn()
    try:
        # simple receipt number
        n = conn.execute("SELECT COUNT(*) FROM fee_payments").fetchone()[0] + 1
        receipt = f"RCT{n:05d}"
        conn.execute(
            "INSERT INTO fee_payments (student_id, fee_id, amount_paid, payment_date, payment_method, receipt_no, session, term, recorded_by, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (student_id, fee_id, amount, date, method, receipt, session, term, recorded_by, note))
        conn.commit()
        return receipt
    except Exception as e:
        return None
    finally:
        conn.close()


def naira(n):
    try:
        return "\u20a6{:,.0f}".format(float(n or 0))
    except Exception:
        return "\u20a60"


# ============================================================
# PHASE 4a - Enrollment (add / edit students)
# ============================================================

def _student_columns():
    """Columns that actually exist on the students table (so we never write a missing column)."""
    conn = get_conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
        return cols
    finally:
        conn.close()


def next_admission_no():
    """Suggest the next admission number based on the highest existing PS/YYYY/NNN."""
    import datetime, re
    conn = get_conn()
    try:
        rows = conn.execute("SELECT admission_no FROM students WHERE admission_no IS NOT NULL").fetchall()
    except Exception:
        conn.close(); return ""
    conn.close()
    year = datetime.date.today().year
    best = 0
    prefix = "PS"
    for r in rows:
        m = re.match(r"([A-Za-z]+)/(\d{4})/(\d+)", (r[0] or "").strip())
        if m:
            prefix = m.group(1)
            n = int(m.group(3))
            if n > best:
                best = n
    return f"{prefix}/{year}/{best+1:03d}"


def add_student(data):
    """Insert a student using only columns that exist. data is a dict."""
    cols = _student_columns()
    fields = [k for k in data.keys() if k in cols]
    if not fields:
        return None
    placeholders = ",".join("?" for _ in fields)
    conn = get_conn()
    try:
        cur = conn.execute(
            f"INSERT INTO students ({','.join(fields)}) VALUES ({placeholders})",
            [data[f] for f in fields])
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        return None
    finally:
        conn.close()


def update_student(student_id, data):
    cols = _student_columns()
    fields = [k for k in data.keys() if k in cols]
    if not fields:
        return False
    sets = ",".join(f"{f}=?" for f in fields)
    conn = get_conn()
    try:
        conn.execute(f"UPDATE students SET {sets} WHERE id=?", [data[f] for f in fields] + [student_id])
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


# ============================================================
# PHASE 4c - Broadsheet (whole-class results with positions)
# ============================================================

def compute_class_broadsheet(class_name):
    """Build a whole-class results grid with totals, averages, grades, positions."""
    students = get_students(active_only=True, class_level=class_name)
    subjects = get_subjects_for_class(class_name)
    subj_names = [s["name"] for s in subjects]
    info = get_school_info()
    mca1 = int(info.get("max_ca1", 20) or 20)
    mca2 = int(info.get("max_ca2", 20) or 20)
    mexam = int(info.get("max_exam", 60) or 60)
    max_total = mca1 + mca2 + mexam

    rows = []
    for st in students:
        scores = {}
        grand = 0; counted = 0
        for subj in subjects:
            sc = get_score(st["id"], subj["id"]) or {}
            ca1 = sc.get("ca1"); ca2 = sc.get("ca2"); exam = sc.get("exam")
            has = any(v is not None and v != "" for v in (ca1, ca2, exam))
            tot = (ca1 or 0) + (ca2 or 0) + (exam or 0)
            scores[subj["name"]] = _n(tot) if has else ""
            if has:
                grand += tot; counted += 1
        avg = round(grand / counted, 1) if counted else 0
        grade, _rem = _grade_for(avg, max_total)
        rows.append({"id": st["id"], "name": st["full_name"], "admission_no": st.get("admission_no"),
                     "scores": scores, "total": _n(grand), "average": _n(avg),
                     "grade": grade if counted else "", "_avg_raw": avg, "_counted": counted})
    # positions by average (desc); ungraded (no scores) get no position
    graded = [r for r in rows if r["_counted"] > 0]
    graded.sort(key=lambda r: r["_avg_raw"], reverse=True)
    pos = 0; last = None; rank = 0
    for r in graded:
        rank += 1
        if r["_avg_raw"] != last:
            pos = rank
            last = r["_avg_raw"]
        r["position"] = pos
    for r in rows:
        if r["_counted"] == 0:
            r["position"] = "-"
    return {"class_name": class_name, "subjects": subj_names, "rows": rows,
            "maxima": {"ca1": mca1, "ca2": mca2, "exam": mexam, "total": max_total}}


# ============================================================
# WhatsApp helpers (wa.me link - free, opens WhatsApp prefilled)
# ============================================================

def wa_number(raw):
    """
    Normalize a Nigerian phone number to wa.me international format (no +).
    Handles: 08030000002 -> 2348030000002 ; +2348030000002 -> 2348030000002 ;
    2348030000002 stays. Picks the FIRST number if several are comma/slash separated.
    """
    import re
    if not raw:
        return ""
    # take the first number if multiple
    first = re.split(r"[,/;]| or ", str(raw))[0]
    digits = re.sub(r"\D", "", first)
    if not digits:
        return ""
    if digits.startswith("234"):
        return digits
    if digits.startswith("0"):
        return "234" + digits[1:]
    if len(digits) == 10:  # 8030000002 without leading 0
        return "234" + digits
    return digits


def result_whatsapp_message(result, school, report_url=None):
    """Build the parent message: greeting + per-subject summary + link to PDF."""
    st = result["student"]
    lines = []
    sname = school.get("name") or "our school"
    lines.append(f"Assalamu Alaykum / Good day.")
    lines.append(f"Result for *{st.get('full_name','')}*"
                 + (f" ({st.get('class_level')})" if st.get('class_level') else "")
                 + f" - {sname}.")
    term = school.get("term"); sess = school.get("session")
    if sess or term:
        lines.append(f"{sess or ''}{(' ' + term + ' term') if term else ''}".strip())
    lines.append("")
    if result["subjects_counted"]:
        for row in result["rows"]:
            if row["total"] != "":
                lines.append(f"- {row['subject']}: {row['total']} ({row['grade']})")
        lines.append("")
        lines.append(f"Total: {result['grand_total']}  |  Average: {result['average']}  |  Grade: {result['overall_grade']}")
    else:
        lines.append("(No scores recorded yet.)")
    if report_url:
        lines.append("")
        lines.append(f"Full report card (PDF): {report_url}")
    lines.append("")
    lines.append("Thank you.")
    return "\n".join(lines)


# ============================================================
# PHASE 4d - Affective / Psychomotor traits + comments
# ============================================================

AFFECTIVE_TRAITS = ["Punctuality", "Neatness", "Politeness", "Honesty",
                    "Cooperation", "Attentiveness", "Self-control"]
PSYCHOMOTOR_TRAITS = ["Handwriting", "Drawing & Painting", "Sports & Games",
                      "Verbal Fluency", "Musical Skills", "Handling of Tools"]
RATING_LABELS = {5: "Excellent", 4: "Very Good", 3: "Good", 2: "Fair", 1: "Poor"}


def _ensure_traits_tables():
    conn = get_conn()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS student_traits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, session TEXT, term TEXT,
            domain TEXT, trait TEXT, rating INTEGER)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS student_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, session TEXT, term TEXT,
            teacher_comment TEXT, head_comment TEXT)""")
        conn.commit()
    finally:
        conn.close()


def get_student_traits(student_id):
    """Return {trait: rating} for the current term (both domains merged)."""
    _ensure_traits_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT trait, rating FROM student_traits WHERE student_id=? AND session=? AND term=?",
            (student_id, session, term)).fetchall()
    finally:
        conn.close()
    return {r["trait"]: r["rating"] for r in rows}


def get_student_comments(student_id):
    _ensure_traits_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        r = conn.execute(
            "SELECT teacher_comment, head_comment FROM student_comments WHERE student_id=? AND session=? AND term=?",
            (student_id, session, term)).fetchone()
    finally:
        conn.close()
    return {"teacher_comment": (r["teacher_comment"] if r else ""),
            "head_comment": (r["head_comment"] if r else "")}


def save_student_traits(student_id, ratings, teacher_comment, head_comment):
    """ratings = {trait: int 1-5 or None}. Saves both domains + comments for current term."""
    _ensure_traits_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        # wipe this term's traits for the student then re-insert (simple + idempotent)
        conn.execute("DELETE FROM student_traits WHERE student_id=? AND session=? AND term=?",
                     (student_id, session, term))
        for trait, rating in ratings.items():
            if rating:
                domain = "affective" if trait in AFFECTIVE_TRAITS else "psychomotor"
                conn.execute(
                    "INSERT INTO student_traits (student_id,session,term,domain,trait,rating) VALUES (?,?,?,?,?,?)",
                    (student_id, session, term, domain, trait, int(rating)))
        # upsert comments
        existing = conn.execute(
            "SELECT id FROM student_comments WHERE student_id=? AND session=? AND term=?",
            (student_id, session, term)).fetchone()
        if existing:
            conn.execute("UPDATE student_comments SET teacher_comment=?, head_comment=? WHERE id=?",
                         (teacher_comment, head_comment, existing[0]))
        else:
            conn.execute(
                "INSERT INTO student_comments (student_id,session,term,teacher_comment,head_comment) VALUES (?,?,?,?,?)",
                (student_id, session, term, teacher_comment, head_comment))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


# ============================================================
# Auto comments (performance-based, like the desktop version)
# ============================================================

def auto_comments(average, max_total=100, grade=None):
    """
    Generate a Class Teacher and Head Teacher comment from the average.
    Mirrors the desktop app's banded remarks.
    """
    pct = (average / max_total * 100) if max_total else 0
    if pct >= 75:
        teacher = "An excellent and hardworking pupil. Keep up the outstanding performance."
        head = "A brilliant result. Highly commended."
    elif pct >= 65:
        teacher = "A very good result. Keep working hard to reach the top."
        head = "A very good performance. Well done."
    elif pct >= 55:
        teacher = "A good result. With more effort, even better is possible."
        head = "A good performance. Keep improving."
    elif pct >= 45:
        teacher = "A fair result. More effort and concentration are needed."
        head = "Fair. There is room for improvement."
    elif pct >= 40:
        teacher = "A weak pass. Needs to study harder and pay more attention in class."
        head = "Weak. Greater effort is required next term."
    else:
        teacher = "Performance is below average. Serious improvement and extra support are needed."
        head = "Poor result. Parental support and more effort are strongly advised."
    return teacher, head


# ============================================================
# PHASE 5 - Theory exams (type answers, on-screen marking, review)
# ============================================================

def _ensure_theory_tables():
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS theory_exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, subject TEXT, class_level TEXT,
            duration_min INTEGER, instructions TEXT, mode TEXT DEFAULT 'type',
            session TEXT, term TEXT, created_by TEXT, created_at TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS theory_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, q_order INTEGER,
            question TEXT, marks REAL DEFAULT 5, model_answer TEXT);
        CREATE TABLE IF NOT EXISTS theory_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, student_id INTEGER,
            started_at TEXT, submitted_at TEXT, status TEXT DEFAULT 'in_progress',
            total_score REAL, total_marks REAL, marked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS theory_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER, question_id INTEGER,
            answer_text TEXT, awarded REAL, marker_note TEXT);
        """)
        conn.commit()
    finally:
        conn.close()


def create_theory_exam(title, subject, class_level, duration_min, instructions, mode, created_by):
    _ensure_theory_tables()
    import datetime
    session, term = _current_session_term()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO theory_exams (title,subject,class_level,duration_min,instructions,mode,session,term,created_by,created_at,active) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
            (title, subject, class_level, duration_min, instructions, mode, session, term,
             created_by, datetime.datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_theory_question(exam_id, question, marks, model_answer=""):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM theory_questions WHERE exam_id=?", (exam_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO theory_questions (exam_id,q_order,question,marks,model_answer) VALUES (?,?,?,?,?)",
            (exam_id, n+1, question, marks, model_answer))
        conn.commit()
        return True
    finally:
        conn.close()


def get_theory_exam(exam_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM theory_exams WHERE id=?", (exam_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_theory_questions(exam_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM theory_questions WHERE exam_id=? ORDER BY q_order", (exam_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_theory_exams(class_level=None):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        if class_level:
            rows = conn.execute("SELECT * FROM theory_exams WHERE active=1 AND class_level=? ORDER BY id DESC", (class_level,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM theory_exams WHERE active=1 ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["n_questions"] = conn.execute("SELECT COUNT(*) FROM theory_questions WHERE exam_id=?", (r["id"],)).fetchone()[0]
            d["total_marks"] = conn.execute("SELECT COALESCE(SUM(marks),0) FROM theory_questions WHERE exam_id=?", (r["id"],)).fetchone()[0]
            out.append(d)
        return out
    finally:
        conn.close()


def start_theory_attempt(exam_id, student_id):
    _ensure_theory_tables()
    import datetime
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM theory_attempts WHERE exam_id=? AND student_id=?", (exam_id, student_id)).fetchone()
        if existing:
            return dict(existing)
        cur = conn.execute(
            "INSERT INTO theory_attempts (exam_id,student_id,started_at,status) VALUES (?,?,?,'in_progress')",
            (exam_id, student_id, datetime.datetime.now().isoformat()))
        conn.commit()
        r = conn.execute("SELECT * FROM theory_attempts WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(r)
    finally:
        conn.close()


def get_theory_attempt(attempt_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM theory_attempts WHERE id=?", (attempt_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def get_attempt_for(exam_id, student_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM theory_attempts WHERE exam_id=? AND student_id=?", (exam_id, student_id)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def save_theory_answer(attempt_id, question_id, answer_text):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        ex = conn.execute("SELECT id FROM theory_answers WHERE attempt_id=? AND question_id=?", (attempt_id, question_id)).fetchone()
        if ex:
            conn.execute("UPDATE theory_answers SET answer_text=? WHERE id=?", (answer_text, ex[0]))
        else:
            conn.execute("INSERT INTO theory_answers (attempt_id,question_id,answer_text) VALUES (?,?,?)",
                         (attempt_id, question_id, answer_text))
        conn.commit()
        return True
    finally:
        conn.close()


def submit_theory_attempt(attempt_id):
    _ensure_theory_tables()
    import datetime
    conn = get_conn()
    try:
        conn.execute("UPDATE theory_attempts SET status='submitted', submitted_at=? WHERE id=?",
                     (datetime.datetime.now().isoformat(), attempt_id))
        conn.commit()
        return True
    finally:
        conn.close()


def get_theory_answers(attempt_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM theory_answers WHERE attempt_id=?", (attempt_id,)).fetchall()
        return {r["question_id"]: dict(r) for r in rows}
    finally:
        conn.close()


def mark_theory_answer(attempt_id, question_id, awarded, note=""):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        ex = conn.execute("SELECT id FROM theory_answers WHERE attempt_id=? AND question_id=?", (attempt_id, question_id)).fetchone()
        if ex:
            conn.execute("UPDATE theory_answers SET awarded=?, marker_note=? WHERE id=?", (awarded, note, ex[0]))
        else:
            conn.execute("INSERT INTO theory_answers (attempt_id,question_id,awarded,marker_note) VALUES (?,?,?,?)",
                         (attempt_id, question_id, awarded, note))
        conn.commit()
    finally:
        conn.close()


def finalize_theory_marking(attempt_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        att = conn.execute("SELECT * FROM theory_attempts WHERE id=?", (attempt_id,)).fetchone()
        if not att:
            return False
        qs = conn.execute("SELECT * FROM theory_questions WHERE exam_id=?", (att["exam_id"],)).fetchall()
        total_marks = sum((q["marks"] or 0) for q in qs)
        ans = conn.execute("SELECT * FROM theory_answers WHERE attempt_id=?", (attempt_id,)).fetchall()
        total_score = sum((a["awarded"] or 0) for a in ans)
        conn.execute("UPDATE theory_attempts SET total_score=?, total_marks=?, marked=1, status='marked' WHERE id=?",
                     (total_score, total_marks, attempt_id))
        conn.commit()
        return True
    finally:
        conn.close()


def list_attempts_for_exam(exam_id):
    _ensure_theory_tables()
    conn = get_conn()
    try:
        rows = conn.execute("""SELECT a.*, s.full_name, s.admission_no
                               FROM theory_attempts a JOIN students s ON s.id=a.student_id
                               WHERE a.exam_id=? ORDER BY s.full_name""", (exam_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# PHASE 6 - MCQ CBT engine (JAMB / WAEC / NECO / School)
# ============================================================

EXAM_PRESETS = {
    "school":  {"label": "School Test/Exam", "subjects": 1,  "per_subject": 20,  "duration": 30},
    "waec":    {"label": "WAEC Practice",    "subjects": 1,  "per_subject": 50,  "duration": 60},
    "neco":    {"label": "NECO Practice",    "subjects": 1,  "per_subject": 50,  "duration": 60},
    "jamb":    {"label": "JAMB/UTME Practice","subjects": 4, "per_subject": 45,  "duration": 120},
}


def _ensure_mcq_tables():
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS mcq_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, exam_type TEXT, subject TEXT,
            question TEXT, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
            answer TEXT, topic TEXT, year TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS mcq_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, exam_type TEXT, class_level TEXT,
            subjects TEXT, n_per_subject INTEGER, duration_min INTEGER,
            link_target TEXT, link_subject TEXT,
            session TEXT, term TEXT, created_by TEXT, created_at TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS mcq_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, test_id INTEGER, student_id INTEGER,
            started_at TEXT, submitted_at TEXT, status TEXT DEFAULT 'in_progress',
            score INTEGER, total INTEGER, question_ids TEXT, pushed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS mcq_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER, question_id INTEGER, chosen TEXT);
        """)
        conn.commit()
    finally:
        conn.close()


def add_mcq_question(exam_type, subject, question, a, b, c, d, answer, topic="", year=""):
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        conn.execute("""INSERT INTO mcq_questions (exam_type,subject,question,option_a,option_b,option_c,option_d,answer,topic,year,active)
                        VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                     (exam_type, subject, question, a, b, c, d, (answer or "").strip().upper()[:1], topic, year))
        conn.commit()
        return True
    finally:
        conn.close()


def mcq_subjects(exam_type=None):
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        if exam_type:
            rows = conn.execute("SELECT DISTINCT subject FROM mcq_questions WHERE active=1 AND exam_type=? AND subject<>'' ORDER BY subject",(exam_type,)).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT subject FROM mcq_questions WHERE active=1 AND subject<>'' ORDER BY subject").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def mcq_question_count(exam_type, subject):
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM mcq_questions WHERE active=1 AND exam_type=? AND subject=?",(exam_type,subject)).fetchone()[0]
    finally:
        conn.close()


def create_mcq_test(title, exam_type, class_level, subjects, n_per_subject, duration_min,
                    link_target, link_subject, created_by):
    _ensure_mcq_tables()
    import datetime, json
    session, term = _current_session_term()
    conn = get_conn()
    try:
        cur = conn.execute("""INSERT INTO mcq_tests (title,exam_type,class_level,subjects,n_per_subject,duration_min,
                              link_target,link_subject,session,term,created_by,created_at,active)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                           (title, exam_type, class_level, json.dumps(subjects), n_per_subject, duration_min,
                            link_target, link_subject, session, term, created_by, datetime.datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_mcq_test(test_id):
    _ensure_mcq_tables()
    import json
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM mcq_tests WHERE id=?", (test_id,)).fetchone()
        if not r: return None
        d = dict(r)
        try: d["subject_list"] = json.loads(d.get("subjects") or "[]")
        except Exception: d["subject_list"] = []
        return d
    finally:
        conn.close()


def list_mcq_tests(class_level=None):
    _ensure_mcq_tables()
    import json
    conn = get_conn()
    try:
        if class_level:
            rows = conn.execute("SELECT * FROM mcq_tests WHERE active=1 AND (class_level=? OR class_level='' OR class_level IS NULL) ORDER BY id DESC",(class_level,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM mcq_tests WHERE active=1 ORDER BY id DESC").fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try: d["subject_list"]=json.loads(d.get("subjects") or "[]")
            except Exception: d["subject_list"]=[]
            out.append(d)
        return out
    finally:
        conn.close()


def assemble_mcq_questions(test):
    """Pick the questions for a test: n_per_subject random per subject."""
    _ensure_mcq_tables()
    import random
    conn = get_conn()
    try:
        chosen=[]
        for subj in test["subject_list"]:
            rows = conn.execute("SELECT id FROM mcq_questions WHERE active=1 AND exam_type=? AND subject=?",
                                (test["exam_type"], subj)).fetchall()
            ids=[r[0] for r in rows]
            random.shuffle(ids)
            chosen += ids[:test["n_per_subject"]]
        return chosen
    finally:
        conn.close()


def get_mcq_questions_by_ids(ids):
    _ensure_mcq_tables()
    if not ids: return []
    conn = get_conn()
    try:
        qmarks=",".join("?"*len(ids))
        rows = conn.execute(f"SELECT * FROM mcq_questions WHERE id IN ({qmarks})", ids).fetchall()
        by_id={r["id"]:dict(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]
    finally:
        conn.close()


def start_mcq_attempt(test_id, student_id):
    _ensure_mcq_tables()
    import datetime, json
    conn = get_conn()
    try:
        ex = conn.execute("SELECT * FROM mcq_attempts WHERE test_id=? AND student_id=?",(test_id,student_id)).fetchone()
        if ex:
            return dict(ex)
        test = get_mcq_test(test_id)
        qids = assemble_mcq_questions(test)
        cur = conn.execute("INSERT INTO mcq_attempts (test_id,student_id,started_at,status,question_ids) VALUES (?,?,?,'in_progress',?)",
                           (test_id, student_id, datetime.datetime.now().isoformat(), json.dumps(qids)))
        conn.commit()
        r = conn.execute("SELECT * FROM mcq_attempts WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(r)
    finally:
        conn.close()


def get_mcq_attempt(attempt_id):
    _ensure_mcq_tables()
    import json
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM mcq_attempts WHERE id=?", (attempt_id,)).fetchone()
        if not r: return None
        d=dict(r)
        try: d["qid_list"]=json.loads(d.get("question_ids") or "[]")
        except Exception: d["qid_list"]=[]
        return d
    finally:
        conn.close()


def submit_mcq_attempt(attempt_id, responses):
    """responses = {question_id: 'A'/'B'/...}. Auto-scores."""
    _ensure_mcq_tables()
    import datetime
    conn = get_conn()
    try:
        att = conn.execute("SELECT * FROM mcq_attempts WHERE id=?", (attempt_id,)).fetchone()
        if not att: return None
        import json
        qids = json.loads(att["question_ids"] or "[]")
        score=0
        for qid in qids:
            chosen=(responses.get(str(qid)) or responses.get(qid) or "").strip().upper()[:1]
            conn.execute("INSERT INTO mcq_responses (attempt_id,question_id,chosen) VALUES (?,?,?)",(attempt_id,qid,chosen))
            row=conn.execute("SELECT answer FROM mcq_questions WHERE id=?",(qid,)).fetchone()
            if row and chosen and chosen==(row[0] or "").strip().upper()[:1]:
                score+=1
        total=len(qids)
        conn.execute("UPDATE mcq_attempts SET status='done', submitted_at=?, score=?, total=? WHERE id=?",
                     (datetime.datetime.now().isoformat(), score, total, attempt_id))
        conn.commit()
        return {"score":score,"total":total}
    finally:
        conn.close()


def list_mcq_attempts_for_test(test_id):
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        rows = conn.execute("""SELECT a.*, s.full_name, s.admission_no FROM mcq_attempts a
                               JOIN students s ON s.id=a.student_id WHERE a.test_id=? ORDER BY s.full_name""",(test_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_mcq_attempt_for(test_id, student_id):
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM mcq_attempts WHERE test_id=? AND student_id=?",(test_id,student_id)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def push_mcq_to_scores(attempt_id):
    """
    Send a finished MCQ attempt's score into academic score entry, scaled to the
    target field's maximum. link_target = 'ca1'|'ca2'|'exam'; link_subject = the
    academic subject name to match. Returns (ok, message).
    """
    _ensure_mcq_tables()
    att = get_mcq_attempt(attempt_id)
    if not att or att["status"] != "done":
        return False, "Attempt not finished."
    test = get_mcq_test(att["test_id"])
    target = (test.get("link_target") or "").lower()
    link_subject = test.get("link_subject") or ""
    if target not in ("ca1","ca2","exam") or not link_subject:
        return False, "This test is not linked to a score field."
    info = get_school_info()
    maxes = {"ca1": int(info.get("max_ca1",20) or 20),
             "ca2": int(info.get("max_ca2",20) or 20),
             "exam": int(info.get("max_exam",60) or 60)}
    cap = maxes[target]
    raw_pct = (att["score"]/att["total"]) if att["total"] else 0
    scaled = round(raw_pct * cap, 1)
    # find the subject_id by name
    conn = get_conn()
    try:
        srow = conn.execute("SELECT id FROM subjects WHERE name=?", (link_subject,)).fetchone()
    finally:
        conn.close()
    if not srow:
        return False, f"Subject '{link_subject}' not found in academic subjects."
    subject_id = srow[0]
    existing = get_score(att["student_id"], subject_id) or {}
    ca1 = existing.get("ca1"); ca2 = existing.get("ca2"); exam = existing.get("exam")
    if target=="ca1": ca1=scaled
    elif target=="ca2": ca2=scaled
    else: exam=scaled
    save_score(att["student_id"], subject_id, ca1, ca2, exam)
    # mark pushed
    conn = get_conn()
    try:
        conn.execute("UPDATE mcq_attempts SET pushed=1 WHERE id=?", (attempt_id,))
        conn.commit()
    finally:
        conn.close()
    return True, f"{att['score']}/{att['total']} -> {scaled}/{cap} into {target.upper()} for {link_subject}."


# ============================================================
# Import existing desktop CBT questions into the web MCQ bank
# ============================================================

def import_desktop_cbt():
    """
    Pull questions from the desktop tables into mcq_questions:
      - cbt_questions  (subject_id -> subject name)  -> exam_type 'school'
      - exam_questions (exam_type, subject)          -> that exam_type
    Skips duplicates (same exam_type+subject+question). Returns a summary dict.
    """
    _ensure_mcq_tables()
    conn = get_conn()
    summary = {"school": 0, "jamb": 0, "waec": 0, "neco": 0, "other": 0, "skipped": 0, "errors": []}

    def exists(et, subj, q):
        r = conn.execute("SELECT 1 FROM mcq_questions WHERE exam_type=? AND subject=? AND question=? LIMIT 1",
                         (et, subj, q)).fetchone()
        return r is not None

    try:
        # subject_id -> name map
        subj_map = {}
        try:
            for r in conn.execute("SELECT id, name FROM subjects").fetchall():
                subj_map[r["id"]] = r["name"]
        except Exception:
            pass

        # 1) cbt_questions -> school
        try:
            rows = conn.execute("SELECT * FROM cbt_questions").fetchall()
        except Exception:
            rows = []
        for r in rows:
            r = dict(r)
            subj = subj_map.get(r.get("subject_id"), "") or "General"
            q = (r.get("question_text") or "").strip()
            if not q:
                continue
            if exists("school", subj, q):
                summary["skipped"] += 1
                continue
            conn.execute("""INSERT INTO mcq_questions (exam_type,subject,question,option_a,option_b,option_c,option_d,answer,topic,active)
                            VALUES ('school',?,?,?,?,?,?,?,?,1)""",
                         (subj, q, r.get("option_a"), r.get("option_b"), r.get("option_c"), r.get("option_d"),
                          (r.get("correct_answer") or "").strip().upper()[:1], r.get("topic") or ""))
            summary["school"] += 1

        # 2) exam_questions -> their exam_type
        try:
            rows = conn.execute("SELECT * FROM exam_questions").fetchall()
        except Exception:
            rows = []
        for r in rows:
            r = dict(r)
            et = (r.get("exam_type") or "").strip().lower() or "school"
            if et not in ("school", "jamb", "waec", "neco"):
                # map common variants
                if "utme" in et or "jamb" in et: et = "jamb"
                elif "waec" in et: et = "waec"
                elif "neco" in et: et = "neco"
                else: et = "school"
            subj = (r.get("subject") or "General").strip()
            q = (r.get("question_text") or "").strip()
            if not q:
                continue
            if exists(et, subj, q):
                summary["skipped"] += 1
                continue
            conn.execute("""INSERT INTO mcq_questions (exam_type,subject,question,option_a,option_b,option_c,option_d,answer,topic,year,active)
                            VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                         (et, subj, q, r.get("option_a"), r.get("option_b"), r.get("option_c"), r.get("option_d"),
                          (r.get("correct_answer") or "").strip().upper()[:1], r.get("topic") or "", r.get("year") or ""))
            summary[et if et in summary else "other"] += 1

        conn.commit()
    except Exception as e:
        summary["errors"].append(str(e))
    finally:
        conn.close()
    return summary



# ============================================================
# Staff "Start CBT" - preview + staff self-attempt
# ============================================================

def list_all_mcq_tests():
    return list_mcq_tests()


def start_staff_mcq_attempt(test_id, staff_key):
    """A staff self-test attempt. Stored with negative student_id to keep it separate."""
    _ensure_mcq_tables()
    import datetime, json
    conn = get_conn()
    try:
        # staff attempts: student_id = -1 * a stable small int from staff_key hash
        sid = -(abs(hash(staff_key)) % 100000 + 1)
        ex = conn.execute("SELECT * FROM mcq_attempts WHERE test_id=? AND student_id=?",(test_id,sid)).fetchone()
        if ex and ex["status"] != "done":
            return dict(ex)
        if ex and ex["status"] == "done":
            # allow a fresh staff retake: delete the old one + its responses
            conn.execute("DELETE FROM mcq_responses WHERE attempt_id=?", (ex["id"],))
            conn.execute("DELETE FROM mcq_attempts WHERE id=?", (ex["id"],))
            conn.commit()
        test = get_mcq_test(test_id)
        qids = assemble_mcq_questions(test)
        cur = conn.execute("INSERT INTO mcq_attempts (test_id,student_id,started_at,status,question_ids) VALUES (?,?,?,'in_progress',?)",
                           (test_id, sid, datetime.datetime.now().isoformat(), json.dumps(qids)))
        conn.commit()
        r = conn.execute("SELECT * FROM mcq_attempts WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(r)
    finally:
        conn.close()


def get_mcq_test_preview(test_id):
    """All questions for a test's subjects (with correct answers) for staff preview."""
    _ensure_mcq_tables()
    test = get_mcq_test(test_id)
    if not test:
        return None, []
    conn = get_conn()
    try:
        qs = []
        for subj in test["subject_list"]:
            rows = conn.execute("SELECT * FROM mcq_questions WHERE active=1 AND exam_type=? AND subject=? LIMIT ?",
                                (test["exam_type"], subj, test["n_per_subject"])).fetchall()
            qs += [dict(r) for r in rows]
        return test, qs
    finally:
        conn.close()


# ============================================================
# PHASE 7 - Local AI-style question generator (offline)
#   Drives off a pasted scheme of work. For each topic it finds related
#   questions in the bank (by topic/keyword match), varies them, and also
#   pulls theory questions. No external API needed.
# ============================================================

import re as _re

_STOP = set("the a an of to in on for and or is are was were be by with from as at this that these those your you their his her its it we they i".split())


def _keywords(text):
    words = _re.findall(r"[A-Za-z]{3,}", (text or "").lower())
    return [w for w in words if w not in _STOP]


def _score_match(topic_kw, text):
    tw = set(_keywords(text))
    if not tw or not topic_kw:
        return 0
    return len(set(topic_kw) & tw)


def parse_scheme(scheme_text):
    """Split a pasted scheme of work into topics (one per line, strip week/numbering)."""
    topics = []
    for line in (scheme_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # strip leading 'Week 1:', '1.', '1)', '-', 'WK1 -' etc.
        line = _re.sub(r"^(week\s*\d+\s*[:\-\.]?|wk\s*\d+\s*[:\-\.]?|\d+\s*[:\.\)\-]\s*|[\-\*\u2022]\s*)", "", line, flags=_re.I).strip()
        if line:
            topics.append(line)
    return topics


def _vary_mcq(q):
    """Produce a light variation of an MCQ: shuffle option order, keep correct mapping."""
    import random
    opts = [("A", q.get("option_a")), ("B", q.get("option_b")),
            ("C", q.get("option_c")), ("D", q.get("option_d"))]
    opts = [(k, v) for k, v in opts if v]
    correct_val = None
    for k, v in opts:
        if k == (q.get("answer") or "").strip().upper()[:1]:
            correct_val = v
    random.shuffle(opts)
    letters = ["A", "B", "C", "D"]
    new = {"question": q.get("question"), "subject": q.get("subject"),
           "topic": q.get("topic"), "option_a": "", "option_b": "", "option_c": "", "option_d": "", "answer": ""}
    for i, (_, v) in enumerate(opts):
        new["option_" + letters[i].lower()] = v
        if v == correct_val:
            new["answer"] = letters[i]
    return new


def generate_mcq_for_topic(exam_type, subject, topic, count=5):
    """Find bank MCQs related to a topic and return up to `count` varied copies."""
    _ensure_mcq_tables()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mcq_questions WHERE active=1 AND exam_type=? AND subject=?",
            (exam_type, subject)).fetchall()
    finally:
        conn.close()
    topic_kw = _keywords(topic)
    scored = []
    for r in rows:
        r = dict(r)
        sc = _score_match(topic_kw, (r.get("topic") or "") + " " + (r.get("question") or ""))
        # exact topic field match gets a boost
        if (r.get("topic") or "").strip().lower() == (topic or "").strip().lower():
            sc += 5
        if sc > 0:
            scored.append((sc, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [r for _, r in scored[:count]]
    # if too few matched, top up with any from the subject
    if len(picked) < count:
        extra = [dict(r) for r in rows if dict(r) not in picked]
        picked += extra[:count - len(picked)]
    return [_vary_mcq(p) for p in picked[:count]]


def generate_theory_for_topic(subject, topic, count=3):
    """Pull related theory questions from theory_questions joined via theory_exams subject,
    plus generate simple scaffold prompts from the topic if the bank is thin."""
    _ensure_theory_tables()
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT tq.question, tq.marks, tq.model_answer, te.subject
               FROM theory_questions tq JOIN theory_exams te ON te.id=tq.exam_id
               WHERE te.subject=?""", (subject,)).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    topic_kw = _keywords(topic)
    scored = []
    for r in rows:
        r = dict(r)
        sc = _score_match(topic_kw, r.get("question") or "")
        if sc > 0:
            scored.append((sc, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [{"question": r["question"], "marks": r.get("marks") or 5, "model_answer": r.get("model_answer") or "", "topic": topic}
           for _, r in scored[:count]]
    # scaffold prompts to reach count (templates around the topic)
    scaffolds = [
        ("Explain the concept of {t} with relevant examples.", 5),
        ("State and discuss FOUR important points about {t}.", 8),
        ("Describe {t} and outline its significance.", 6),
        ("With suitable examples, distinguish key ideas relating to {t}.", 6),
    ]
    i = 0
    while len(out) < count and i < len(scaffolds):
        tmpl, mk = scaffolds[i]
        out.append({"question": tmpl.format(t=topic), "marks": mk, "model_answer": "", "topic": topic})
        i += 1
    return out[:count]


def generate_from_scheme(exam_type, subject, scheme_text, mcq_per=5, theory_per=2):
    """For each topic in the scheme, build MCQ + theory sets. Returns a list per topic."""
    topics = parse_scheme(scheme_text)
    result = []
    for t in topics:
        result.append({
            "topic": t,
            "mcq": generate_mcq_for_topic(exam_type, subject, t, mcq_per),
            "theory": generate_theory_for_topic(subject, t, theory_per),
        })
    return result


# ============================================================
# PHASE 8a - Debtors & Arrears
#   current = this term's outstanding; arrears = unpaid from PAST terms.
# ============================================================

TERM_ORDER = ["1st", "2nd", "3rd"]


def _past_terms(session, term):
    """Return (session, term) pairs that come BEFORE the current term.
    Simplified: same session, earlier terms in TERM_ORDER."""
    out = []
    t = (term or "").strip().lower().replace(" term", "")
    # normalize like '1st','2nd','3rd'
    cur_idx = None
    for i, x in enumerate(TERM_ORDER):
        if x in t:
            cur_idx = i
            break
    if cur_idx is None:
        return out
    for i in range(cur_idx):
        out.append((session, TERM_ORDER[i]))
    return out


def _fees_due_for(student, session, term):
    fees = get_fees_for_class(student.get("class_level"), session, term)
    return sum((f.get("amount") or 0) for f in fees)


def _paid_for(student_id, session, term):
    payments = get_student_payments(student_id, session, term)
    return sum((p.get("amount_paid") or 0) for p in payments)


def get_student_arrears(student):
    """Sum of unpaid balances from past terms in the current session."""
    session, term = _current_session_term()
    total = 0.0
    detail = []
    for (s, t) in _past_terms(session, term):
        due = _fees_due_for(student, s, t)
        paid = _paid_for(student["id"], s, t)
        bal = due - paid
        if bal > 0:
            total += bal
            detail.append({"session": s, "term": t, "due": due, "paid": paid, "balance": bal})
    return total, detail


def get_debtors_overview(class_level=None, search=None):
    """Each student: current-term balance + arrears (past terms), shown separately."""
    students = get_students(active_only=True, class_level=class_level, search=search)
    rows = []
    tot_current = tot_arrears = 0.0
    for s in students:
        summ = get_student_fee_summary(s["id"])
        current = summ["balance"] if summ else 0
        arrears, _detail = get_student_arrears(s)
        if current <= 0 and arrears <= 0:
            continue  # not a debtor
        rows.append({
            "id": s["id"], "full_name": s["full_name"], "admission_no": s.get("admission_no"),
            "class_level": s.get("class_level"), "parent_phone": s.get("parent_phone"),
            "current": max(current, 0), "arrears": arrears, "total": max(current, 0) + arrears,
        })
        tot_current += max(current, 0); tot_arrears += arrears
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"rows": rows, "tot_current": tot_current, "tot_arrears": tot_arrears,
            "tot_all": tot_current + tot_arrears, "count": len(rows)}


def debtor_whatsapp(student_row, school):
    """Reminder message for a debtor with current + arrears breakdown."""
    num = wa_number(student_row.get("parent_phone"))
    if not num:
        return ""
    import urllib.parse as _up
    sname = school.get("name") or "the school"
    lines = ["Assalamu Alaykum / Good day."]
    lines.append(f"This is a fee reminder for *{student_row['full_name']}*"
                 + (f" ({student_row['class_level']})" if student_row.get('class_level') else "") + ".")
    if student_row.get("arrears", 0) > 0:
        lines.append(f"Arrears (previous terms): {naira(student_row['arrears'])}")
    if student_row.get("current", 0) > 0:
        lines.append(f"This term's balance: {naira(student_row['current'])}")
    lines.append(f"Total outstanding: {naira(student_row['total'])}")
    lines.append("")
    lines.append(f"Kindly settle the outstanding fees at {sname}. Thank you.")
    return f"https://wa.me/{num}?text={_up.quote(chr(10).join(lines))}"


# ============================================================
# PHASE 8b - Expenses  (uses the REAL desktop `expenses` table)
# ============================================================
#   real columns: title, amount, category, expense_date, session, term,
#   payment_method, vendor, receipt_no, recorded_by, note, receipt_file
#   categories come from expense_categories(name, active, sort_order)

def _ensure_expense_tables():
    """Create the desktop-compatible expenses + expense_categories tables if missing,
    so the web app works even on a fresh DB but matches the desktop schema exactly."""
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, amount REAL, category TEXT,
            expense_date TEXT, session TEXT, term TEXT, payment_method TEXT, vendor TEXT,
            receipt_no TEXT, recorded_by TEXT, note TEXT, receipt_file TEXT);
        CREATE TABLE IF NOT EXISTS expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT,
            sort_order INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
        """)
        conn.commit()
    finally:
        conn.close()


_DEFAULT_EXPENSE_CATEGORIES = ["Salaries", "Supplies", "Maintenance", "Utilities",
                               "Transport", "Rent", "Feeding", "Examination", "Others"]


def get_expense_categories():
    """Pull active categories from expense_categories; fall back to defaults if empty."""
    _ensure_expense_tables()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT name FROM expense_categories WHERE active=1 ORDER BY sort_order, name").fetchall()
        names = [r[0] for r in rows if r[0]]
        return names if names else _DEFAULT_EXPENSE_CATEGORIES
    except Exception:
        return _DEFAULT_EXPENSE_CATEGORIES
    finally:
        conn.close()


# kept for backward-compat references in templates/routes
EXPENSE_CATEGORIES = _DEFAULT_EXPENSE_CATEGORIES


def add_expense(expense_date, category, title, amount, vendor, payment_method, recorded_by,
                note="", receipt_no=""):
    _ensure_expense_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        conn.execute("""INSERT INTO expenses
            (title,amount,category,expense_date,session,term,payment_method,vendor,receipt_no,recorded_by,note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (title, amount, category, expense_date, session, term, payment_method, vendor, receipt_no, recorded_by, note))
        conn.commit()
        return True
    finally:
        conn.close()


def list_expenses(term_only=True, category=None):
    _ensure_expense_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        q = "SELECT * FROM expenses"
        where = []; params = []
        if term_only:
            where.append("session=? AND term=?"); params += [session, term]
        if category and category != "All":
            where.append("category=?"); params.append(category)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY expense_date DESC, id DESC"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_expense(expense_id):
    _ensure_expense_tables()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def expenses_total(term_only=True):
    _ensure_expense_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        if term_only:
            r = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE session=? AND term=?", (session, term)).fetchone()
        else:
            r = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()
        return r[0] or 0
    finally:
        conn.close()


def expenses_by_category(term_only=True):
    _ensure_expense_tables()
    session, term = _current_session_term()
    conn = get_conn()
    try:
        if term_only:
            rows = conn.execute("""SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses
                                   WHERE session=? AND term=? GROUP BY category ORDER BY total DESC""", (session, term)).fetchall()
        else:
            rows = conn.execute("SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses GROUP BY category ORDER BY total DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# PHASE 8c - Accounts & Report (income vs expenses)
# ============================================================

def fees_collected_total(term_only=True):
    """Total fee payments (income) for the current term or all-time."""
    session, term = _current_session_term()
    conn = get_conn()
    try:
        if term_only:
            r = conn.execute("SELECT COALESCE(SUM(amount_paid),0) FROM fee_payments WHERE session=? AND term=?", (session, term)).fetchone()
        else:
            r = conn.execute("SELECT COALESCE(SUM(amount_paid),0) FROM fee_payments").fetchone()
        return r[0] or 0
    except Exception:
        return 0
    finally:
        conn.close()


def get_accounts_summary(term_only=True):
    income = fees_collected_total(term_only)
    expense = expenses_total(term_only)
    by_cat = expenses_by_category(term_only)
    session, term = _current_session_term()
    # also expected fees (total due across active students this term) for context
    expected = 0.0
    outstanding = 0.0
    if term_only:
        for s in get_students(active_only=True):
            summ = get_student_fee_summary(s["id"])
            if summ:
                expected += summ["net_due"]
                if summ["balance"] > 0:
                    outstanding += summ["balance"]
    return {
        "session": session, "term": term,
        "income": income, "expense": expense, "balance": income - expense,
        "expected": expected, "outstanding": outstanding,
        "by_category": by_cat,
    }
