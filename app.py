"""
ParagonEdu Web - Phase 1
FastAPI + server-rendered HTML. Login, dashboard, students (list + detail).
Reuses webdb (which mirrors the desktop app's schema/auth).
"""
import os
from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import webdb

BASE = os.path.dirname(os.path.abspath(__file__))
webdb.ensure_demo_db()

app = FastAPI(title="ParagonEdu Web")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("PARAGON_SECRET", "dev-secret-change-in-production"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))


def current_user(request: Request):
    return request.session.get("user")


def require_login(request: Request):
    u = current_user(request)
    if not u:
        return None
    return u


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "login.html", {"school": school, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("admin")):
    user = webdb.authenticate(username, password)
    school = webdb.get_school_info()
    if not user:
        return templates.TemplateResponse(request, "login.html", {"school": school, "error": "Invalid username or password."})
    if user.get("role") != role:
        return templates.TemplateResponse(request, "login.html", {"school": school, "error": f"This is not a {role} account."})
    request.session["user"] = {"id": user["id"], "username": user["username"], "role": user["role"], "name": user.get("display_name") or user["username"]}
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    counts = webdb.get_dashboard_counts()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "dashboard.html", {"user": u, "counts": counts, "school": school})


@app.get("/students", response_class=HTMLResponse)
def students(request: Request, class_level: str = "All", q: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    rows = webdb.get_students(class_level=class_level, search=q or None)
    classes = ["All"] + webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "students.html", {
        "user": u, "students": rows, "classes": classes,
        "selected_class": class_level, "search": q, "school": school})


@app.get("/students/new", response_class=HTMLResponse)
def student_new_form(request: Request):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _enroll_allowed(u):
        return HTMLResponse("Only admin can enroll students.", status_code=403)
    classes = webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "student_form.html", {
        "user": u, "school": school, "classes": classes, "mode": "new",
        "s": {"admission_no": webdb.next_admission_no()}, "errors": None})


@app.post("/students/new")
async def student_new_save(request: Request):
    u = require_login(request)
    if not u or not _enroll_allowed(u):
        return HTMLResponse("Not allowed", status_code=403)
    form = await request.form()
    data = {k: (form.get(k) or "").strip() for k in
            ["full_name","admission_no","gender","class_level","parent_phone","parent_name","date_of_birth"]}
    errors = []
    if not data["full_name"]:
        errors.append("Full name is required.")
    if not data["class_level"]:
        errors.append("Class is required.")
    school = webdb.get_school_info()
    if errors:
        classes = webdb.get_all_class_names()
        return templates.TemplateResponse(request, "student_form.html", {
            "user": u, "school": school, "classes": classes, "mode": "new", "s": data, "errors": errors})
    data["active"] = 1
    sid = webdb.add_student(data)
    if not sid:
        classes = webdb.get_all_class_names()
        return templates.TemplateResponse(request, "student_form.html", {
            "user": u, "school": school, "classes": classes, "mode": "new", "s": data,
            "errors": ["Could not save the student. Please try again."]})
    return RedirectResponse(f"/students/{sid}", status_code=302)


@app.get("/students/{student_id}", response_class=HTMLResponse)
def student_detail(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    s = webdb.get_student(student_id)
    school = webdb.get_school_info()
    if not s:
        return HTMLResponse("Student not found", status_code=404)
    return templates.TemplateResponse(request, "student_detail.html", {"user": u, "s": s, "school": school})


# ============================================================
# PHASE 2 - Results + Scores
# ============================================================

@app.get("/results", response_class=HTMLResponse)
def results_index(request: Request, class_level: str = "All", q: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    # Students see only their OWN result -> jump straight to it
    if u["role"] == "student":
        # find their student_id
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        if row and row[0]:
            return RedirectResponse(f"/results/{row[0]}", status_code=302)
        return HTMLResponse("No student record linked to this account.", status_code=404)
    # admin/teacher: pick a student
    rows = webdb.get_students(class_level=class_level, search=q or None)
    classes = ["All"] + webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "results_index.html", {
        "user": u, "students": rows, "classes": classes,
        "selected_class": class_level, "search": q, "school": school})


@app.get("/results/{student_id}", response_class=HTMLResponse)
def results_view(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    # students can only see their own
    if u["role"] == "student":
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        own = row[0] if row else None
        if own != student_id:
            return HTMLResponse("You can only view your own result.", status_code=403)
    result = webdb.compute_student_result(student_id)
    school = webdb.get_school_info()
    if not result:
        return HTMLResponse("Student not found", status_code=404)
    # WhatsApp: build a wa.me link to the parent with summary + PDF link
    wa_link = ""
    parent_raw = result["student"].get("parent_phone")
    num = webdb.wa_number(parent_raw)
    if num:
        import urllib.parse as _up
        base_url = str(request.base_url).rstrip("/")
        report_url = f"{base_url}/results/{student_id}/report.pdf"
        msg = webdb.result_whatsapp_message(result, school, report_url)
        wa_link = f"https://wa.me/{num}?text={_up.quote(msg)}"
    return templates.TemplateResponse(request, "result_view.html", {
        "user": u, "r": result, "school": school, "wa_link": wa_link})


@app.get("/scores", response_class=HTMLResponse)
def scores_index(request: Request, class_level: str = "All", q: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Students cannot enter scores.", status_code=403)
    rows = webdb.get_students(class_level=class_level, search=q or None)
    classes = ["All"] + webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "scores_index.html", {
        "user": u, "students": rows, "classes": classes,
        "selected_class": class_level, "search": q, "school": school})


@app.get("/scores/{student_id}", response_class=HTMLResponse)
def scores_entry(request: Request, student_id: int, saved: int = 0):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Students cannot enter scores.", status_code=403)
    student = webdb.get_student(student_id)
    if not student:
        return HTMLResponse("Student not found", status_code=404)
    subjects = webdb.get_student_subjects_for_scoring(student)
    info = webdb.get_school_info()
    # attach current scores
    items = []
    for subj in subjects:
        sc = webdb.get_score(student_id, subj["id"]) or {}
        def _ci(v):
            if v is None: return ""
            try:
                f=float(v); return int(f) if f==int(f) else f
            except: return v
        items.append({"id": subj["id"], "name": subj["name"],
                      "ca1": _ci(sc.get("ca1")), "ca2": _ci(sc.get("ca2")), "exam": _ci(sc.get("exam"))})
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "scores_entry.html", {
        "user": u, "student": student, "items": items, "info": info,
        "school": school, "saved": saved})


@app.post("/scores/{student_id}")
async def scores_save(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Not allowed", status_code=403)
    form = await request.form()
    student = webdb.get_student(student_id)
    if not student:
        return HTMLResponse("Student not found", status_code=404)
    subjects = webdb.get_student_subjects_for_scoring(student)
    info = webdb.get_school_info()
    mca1 = int(info.get("max_ca1", 20) or 20)
    mca2 = int(info.get("max_ca2", 20) or 20)
    mexam = int(info.get("max_exam", 60) or 60)
    maxes = {"ca1": mca1, "ca2": mca2, "exam": mexam}
    labels = {"ca1": "CA1", "ca2": "CA2", "exam": "Exam"}

    def num(v):
        v = (v or "").strip()
        if v == "":
            return None, False
        try:
            return float(v), True
        except ValueError:
            return None, "bad"

    errors = []
    to_save = []          # (sid, ca1, ca2, exam) validated rows
    entered = {}          # echo back what the user typed, per subject
    for subj in subjects:
        sid = subj["id"]
        row_vals = {}
        ok_row = True
        vals = {}
        for field in ("ca1", "ca2", "exam"):
            raw = form.get(f"{field}_{sid}")
            row_vals[field] = (raw or "").strip()
            val, status = num(raw)
            if status == "bad":
                errors.append(f"{subj['name']} {labels[field]}: '{raw}' is not a number.")
                ok_row = False
            elif val is not None:
                if val < 0:
                    errors.append(f"{subj['name']} {labels[field]}: cannot be negative.")
                    ok_row = False
                elif val > maxes[field]:
                    errors.append(f"{subj['name']} {labels[field]}: {int(val) if val==int(val) else val} is above the maximum of {maxes[field]}.")
                    ok_row = False
            vals[field] = val
        entered[sid] = row_vals
        if ok_row and any(vals[f] is not None for f in ("ca1", "ca2", "exam")):
            to_save.append((sid, vals["ca1"], vals["ca2"], vals["exam"]))

    if errors:
        # re-render the form with the errors and what they typed; save nothing
        items = []
        for subj in subjects:
            ev = entered.get(subj["id"], {})
            items.append({"id": subj["id"], "name": subj["name"],
                          "ca1": ev.get("ca1", ""), "ca2": ev.get("ca2", ""), "exam": ev.get("exam", "")})
        school = webdb.get_school_info()
        return templates.TemplateResponse(request, "scores_entry.html", {
            "user": u, "student": student, "items": items, "info": info,
            "school": school, "saved": 0, "errors": errors})

    for sid, ca1, ca2, exam in to_save:
        webdb.save_score(student_id, sid, ca1, ca2, exam)
    return RedirectResponse(f"/scores/{student_id}?saved=1", status_code=302)


# ============================================================
# PHASE 3 - Fees (admin/bursar only)
# ============================================================

def _fees_allowed(u):
    return u and u.get("role") in ("admin", "bursar")


@app.get("/fees", response_class=HTMLResponse)
def fees_overview(request: Request, class_level: str = "All", q: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar can view fees.", status_code=403)
    data = webdb.get_fees_overview(class_level=class_level, search=q or None)
    classes = ["All"] + webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "fees_overview.html", {
        "user": u, "data": data, "classes": classes,
        "selected_class": class_level, "search": q, "school": school, "naira": webdb.naira})


@app.get("/fees/{student_id}", response_class=HTMLResponse)
def fees_student(request: Request, student_id: int, saved: int = 0, receipt: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar can view fees.", status_code=403)
    summ = webdb.get_student_fee_summary(student_id)
    if not summ:
        return HTMLResponse("Student not found", status_code=404)
    school = webdb.get_school_info()
    from datetime import date as _date
    return templates.TemplateResponse(request, "fees_student.html", {
        "user": u, "s": summ, "school": school, "naira": webdb.naira,
        "saved": saved, "receipt": receipt, "today": _date.today().isoformat(), "errors": None})


@app.post("/fees/{student_id}")
async def fees_record(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _fees_allowed(u):
        return HTMLResponse("Not allowed", status_code=403)
    form = await request.form()
    summ = webdb.get_student_fee_summary(student_id)
    if not summ:
        return HTMLResponse("Student not found", status_code=404)
    school = webdb.get_school_info()
    from datetime import date as _date

    errors = []
    raw_amt = (form.get("amount") or "").strip()
    method = (form.get("method") or "Cash").strip()
    pdate = (form.get("date") or _date.today().isoformat()).strip()
    note = (form.get("note") or "").strip()
    amount = None
    try:
        amount = float(raw_amt)
    except ValueError:
        errors.append(f"Amount '{raw_amt}' is not a valid number.")
    if amount is not None:
        if amount <= 0:
            errors.append("Amount must be greater than zero.")

    if errors:
        return templates.TemplateResponse(request, "fees_student.html", {
            "user": u, "s": summ, "school": school, "naira": webdb.naira,
            "saved": 0, "receipt": "", "today": _date.today().isoformat(), "errors": errors})

    receipt = webdb.record_payment(student_id, amount, method, pdate, note, u.get("name") or u.get("username"))
    if not receipt:
        return templates.TemplateResponse(request, "fees_student.html", {
            "user": u, "s": summ, "school": school, "naira": webdb.naira,
            "saved": 0, "receipt": "", "today": _date.today().isoformat(),
            "errors": ["Could not save the payment. Please try again."]})
    return RedirectResponse(f"/fees/{student_id}?saved=1&receipt={receipt}", status_code=302)


# ============================================================
# PHASE 4a - Enrollment (add / edit + admission form PDF)
# ============================================================

def _enroll_allowed(u):
    return u and u.get("role") in ("admin", "bursar")


@app.get("/students/{student_id}/edit", response_class=HTMLResponse)
def student_edit_form(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _enroll_allowed(u):
        return HTMLResponse("Only admin can edit students.", status_code=403)
    s = webdb.get_student(student_id)
    if not s:
        return HTMLResponse("Student not found", status_code=404)
    classes = webdb.get_all_class_names()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "student_form.html", {
        "user": u, "school": school, "classes": classes, "mode": "edit", "s": s, "errors": None})


@app.post("/students/{student_id}/edit")
async def student_edit_save(request: Request, student_id: int):
    u = require_login(request)
    if not u or not _enroll_allowed(u):
        return HTMLResponse("Not allowed", status_code=403)
    form = await request.form()
    data = {k: (form.get(k) or "").strip() for k in
            ["full_name","admission_no","gender","class_level","parent_phone","parent_name","date_of_birth"]}
    errors = []
    if not data["full_name"]:
        errors.append("Full name is required.")
    school = webdb.get_school_info()
    if errors:
        classes = webdb.get_all_class_names()
        data["id"] = student_id
        return templates.TemplateResponse(request, "student_form.html", {
            "user": u, "school": school, "classes": classes, "mode": "edit", "s": data, "errors": errors})
    webdb.update_student(student_id, data)
    return RedirectResponse(f"/students/{student_id}", status_code=302)


@app.get("/students/{student_id}/admission.pdf")
def admission_pdf(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    s = webdb.get_student(student_id)
    if not s:
        return HTMLResponse("Student not found", status_code=404)
    school = webdb.get_school_info()
    import pdfgen
    buf = pdfgen.admission_form(school, s)
    fname = f"Admission_{(s.get('full_name') or 'student').replace(' ','_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={fname}"})


# ============================================================
# PHASE 4b/4c - Report card PDF + Broadsheet
# ============================================================

@app.get("/results/{student_id}/report.pdf")
def report_pdf(request: Request, student_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    # students can only download their own
    if u["role"] == "student":
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        if not row or row[0] != student_id:
            return HTMLResponse("You can only download your own report.", status_code=403)
    r = webdb.compute_student_result(student_id)
    if not r:
        return HTMLResponse("Student not found", status_code=404)
    school = webdb.get_school_info()
    import pdfgen, os
    # logo: look for static/logo.png (or .jpg) - drop your school logo there
    logo_path = None
    for cand in ("logo.png", "logo.jpg", "logo.jpeg"):
        p = os.path.join(BASE, "static", cand)
        if os.path.exists(p):
            logo_path = p; break
    if not logo_path:
        lp = school.get("logo_path")
        if lp and os.path.exists(lp):
            logo_path = lp
    buf = pdfgen.report_card(r, school, logo_path=logo_path)
    fname = f"Report_{(r['student'].get('full_name') or 'student').replace(' ','_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={fname}"})


@app.get("/broadsheet", response_class=HTMLResponse)
def broadsheet_index(request: Request, class_level: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Not available.", status_code=403)
    classes = webdb.get_all_class_names()
    school = webdb.get_school_info()
    data = None
    if class_level and class_level != "":
        data = webdb.compute_class_broadsheet(class_level)
    return templates.TemplateResponse(request, "broadsheet.html", {
        "user": u, "classes": classes, "selected_class": class_level, "data": data, "school": school})


@app.get("/broadsheet/{class_level}/sheet.pdf")
def broadsheet_pdf(request: Request, class_level: str):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Not available.", status_code=403)
    data = webdb.compute_class_broadsheet(class_level)
    school = webdb.get_school_info()
    import pdfgen
    buf = pdfgen.broadsheet(class_level, data["subjects"], data["rows"], school, data["maxima"])
    fname = f"Broadsheet_{class_level.replace(' ','_').replace('.','')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={fname}"})


# ============================================================
# PHASE 4d - Traits & comments entry (admin/teacher)
# ============================================================

@app.get("/traits/{student_id}", response_class=HTMLResponse)
def traits_form(request: Request, student_id: int, saved: int = 0):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] == "student":
        return HTMLResponse("Not allowed.", status_code=403)
    student = webdb.get_student(student_id)
    if not student:
        return HTMLResponse("Student not found", status_code=404)
    ratings = webdb.get_student_traits(student_id)
    comments = webdb.get_student_comments(student_id)
    # if no comment saved yet, pre-fill an auto comment from the result so the
    # teacher sees a sensible default they can keep or edit
    if not comments.get("teacher_comment") or not comments.get("head_comment"):
        res = webdb.compute_student_result(student_id)
        if res and res.get("subjects_counted"):
            at, ah = webdb.auto_comments(
                res["average"] if isinstance(res["average"], (int, float)) else 0,
                res["maxima"]["total"])
            if not comments.get("teacher_comment"):
                comments["teacher_comment"] = at
            if not comments.get("head_comment"):
                comments["head_comment"] = ah
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "traits_form.html", {
        "user": u, "student": student, "school": school,
        "affective": webdb.AFFECTIVE_TRAITS, "psychomotor": webdb.PSYCHOMOTOR_TRAITS,
        "labels": webdb.RATING_LABELS, "ratings": ratings, "comments": comments, "saved": saved})


@app.post("/traits/{student_id}")
async def traits_save(request: Request, student_id: int):
    u = require_login(request)
    if not u or u["role"] == "student":
        return HTMLResponse("Not allowed", status_code=403)
    form = await request.form()
    student = webdb.get_student(student_id)
    if not student:
        return HTMLResponse("Student not found", status_code=404)
    ratings = {}
    for trait in webdb.AFFECTIVE_TRAITS + webdb.PSYCHOMOTOR_TRAITS:
        v = (form.get(f"r_{trait}") or "").strip()
        ratings[trait] = int(v) if v.isdigit() else None
    webdb.save_student_traits(student_id, ratings,
                              (form.get("teacher_comment") or "").strip(),
                              (form.get("head_comment") or "").strip())
    return RedirectResponse(f"/traits/{student_id}?saved=1", status_code=302)


# ============================================================
# PHASE 5 - Theory exams
# ============================================================

def _teacher(u):
    return u and u.get("role") in ("admin", "teacher", "bursar")


@app.get("/theory", response_class=HTMLResponse)
def theory_index(request: Request):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    school = webdb.get_school_info()
    if u["role"] == "student":
        # students see exams for their class they can take
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        sid = row[0] if row else None
        st = webdb.get_student(sid) if sid else None
        exams = webdb.list_theory_exams(class_level=(st.get("class_level") if st else None))
        # annotate with attempt status
        for e in exams:
            att = webdb.get_attempt_for(e["id"], sid) if sid else None
            e["attempt_status"] = att["status"] if att else "not_started"
            e["attempt_id"] = att["id"] if att else None
        return templates.TemplateResponse(request, "theory_student.html", {
            "user": u, "school": school, "exams": exams, "student_id": sid})
    # teacher/admin
    exams = webdb.list_theory_exams()
    return templates.TemplateResponse(request, "theory_index.html", {
        "user": u, "school": school, "exams": exams})


@app.get("/theory/new", response_class=HTMLResponse)
def theory_new(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff can create exams.", status_code=403)
    classes = webdb.get_all_class_names()
    subjects = [s["name"] for s in webdb.get_subjects(included_only=True)]
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_new.html", {
        "user": u, "school": school, "classes": classes, "subjects": subjects})


@app.post("/theory/new")
async def theory_new_save(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    try:
        dur = int(f.get("duration_min") or 60)
    except ValueError:
        dur = 60
    eid = webdb.create_theory_exam(
        (f.get("title") or "Theory Exam").strip(), (f.get("subject") or "").strip(),
        (f.get("class_level") or "").strip(), dur, (f.get("instructions") or "").strip(),
        (f.get("mode") or "type").strip(), u.get("name") or u.get("username"))
    return RedirectResponse(f"/theory/{eid}/questions", status_code=302)


@app.get("/theory/{exam_id}/questions", response_class=HTMLResponse)
def theory_questions(request: Request, exam_id: int, added: int = 0):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    exam = webdb.get_theory_exam(exam_id)
    if not exam:
        return HTMLResponse("Exam not found", status_code=404)
    qs = webdb.get_theory_questions(exam_id)
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_questions.html", {
        "user": u, "school": school, "exam": exam, "questions": qs, "added": added})


@app.post("/theory/{exam_id}/questions")
async def theory_add_question(request: Request, exam_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    try:
        marks = float(f.get("marks") or 5)
    except ValueError:
        marks = 5
    q = (f.get("question") or "").strip()
    if q:
        webdb.add_theory_question(exam_id, q, marks, (f.get("model_answer") or "").strip())
    return RedirectResponse(f"/theory/{exam_id}/questions?added=1", status_code=302)


@app.get("/theory/{exam_id}/take", response_class=HTMLResponse)
def theory_take(request: Request, exam_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] != "student":
        return HTMLResponse("Only students take exams. Staff can preview via the questions page.", status_code=403)
    conn = webdb.get_conn()
    row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
    conn.close()
    sid = row[0] if row else None
    if not sid:
        return HTMLResponse("No student record linked.", status_code=404)
    exam = webdb.get_theory_exam(exam_id)
    if not exam:
        return HTMLResponse("Exam not found", status_code=404)
    attempt = webdb.start_theory_attempt(exam_id, sid)
    if attempt.get("status") in ("submitted", "marked"):
        return RedirectResponse(f"/theory/review/{attempt['id']}", status_code=302)
    qs = webdb.get_theory_questions(exam_id)
    saved = webdb.get_theory_answers(attempt["id"])
    # remaining seconds from started_at + duration
    import datetime
    started = datetime.datetime.fromisoformat(attempt["started_at"])
    elapsed = (datetime.datetime.now() - started).total_seconds()
    remaining = max(0, int(exam["duration_min"] * 60 - elapsed))
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_take.html", {
        "user": u, "school": school, "exam": exam, "questions": qs,
        "attempt": attempt, "saved": saved, "remaining": remaining})


@app.post("/theory/{exam_id}/submit")
async def theory_submit(request: Request, exam_id: int):
    u = require_login(request)
    if not u or u["role"] != "student":
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    attempt_id = int(f.get("attempt_id"))
    # save all answers
    for key in f.keys():
        if key.startswith("ans_"):
            qid = int(key[4:])
            webdb.save_theory_answer(attempt_id, qid, (f.get(key) or "").strip())
    webdb.submit_theory_attempt(attempt_id)
    return RedirectResponse(f"/theory/review/{attempt_id}", status_code=302)


@app.get("/theory/{exam_id}/scripts", response_class=HTMLResponse)
def theory_scripts(request: Request, exam_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    exam = webdb.get_theory_exam(exam_id)
    attempts = webdb.list_attempts_for_exam(exam_id)
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_scripts.html", {
        "user": u, "school": school, "exam": exam, "attempts": attempts})


@app.get("/theory/mark/{attempt_id}", response_class=HTMLResponse)
def theory_mark(request: Request, attempt_id: int, saved: int = 0):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    attempt = webdb.get_theory_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)
    exam = webdb.get_theory_exam(attempt["exam_id"])
    qs = webdb.get_theory_questions(attempt["exam_id"])
    answers = webdb.get_theory_answers(attempt_id)
    student = webdb.get_student(attempt["student_id"])
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_mark.html", {
        "user": u, "school": school, "exam": exam, "questions": qs,
        "answers": answers, "attempt": attempt, "student": student, "saved": saved})


@app.post("/theory/mark/{attempt_id}")
async def theory_mark_save(request: Request, attempt_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    attempt = webdb.get_theory_attempt(attempt_id)
    qs = webdb.get_theory_questions(attempt["exam_id"])
    for q in qs:
        raw = (f.get(f"mark_{q['id']}") or "").strip()
        note = (f.get(f"note_{q['id']}") or "").strip()
        awarded = None
        try:
            awarded = float(raw) if raw != "" else 0
        except ValueError:
            awarded = 0
        # cap at question marks
        awarded = max(0, min(awarded, q["marks"] or 0))
        webdb.mark_theory_answer(attempt_id, q["id"], awarded, note)
    webdb.finalize_theory_marking(attempt_id)
    return RedirectResponse(f"/theory/mark/{attempt_id}?saved=1", status_code=302)


@app.get("/theory/review/{attempt_id}", response_class=HTMLResponse)
def theory_review(request: Request, attempt_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    attempt = webdb.get_theory_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)
    # students can only see their own
    if u["role"] == "student":
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        if not row or row[0] != attempt["student_id"]:
            return HTMLResponse("You can only view your own script.", status_code=403)
    exam = webdb.get_theory_exam(attempt["exam_id"])
    qs = webdb.get_theory_questions(attempt["exam_id"])
    answers = webdb.get_theory_answers(attempt_id)
    student = webdb.get_student(attempt["student_id"])
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "theory_review.html", {
        "user": u, "school": school, "exam": exam, "questions": qs,
        "answers": answers, "attempt": attempt, "student": student})


# ============================================================
# PHASE 6 - MCQ CBT (JAMB / WAEC / NECO / School)
# ============================================================

@app.get("/cbt", response_class=HTMLResponse)
def cbt_index(request: Request):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    school = webdb.get_school_info()
    if u["role"] == "student":
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        sid = row[0] if row else None
        st = webdb.get_student(sid) if sid else None
        tests = webdb.list_mcq_tests(class_level=(st.get("class_level") if st else None))
        for t in tests:
            att = webdb.get_mcq_attempt_for(t["id"], sid) if sid else None
            t["attempt_status"] = att["status"] if att else "not_started"
            t["attempt_id"] = att["id"] if att else None
            t["score"] = att["score"] if att and att.get("score") is not None else None
            t["total"] = att["total"] if att else None
        return templates.TemplateResponse(request, "cbt_student.html", {"user": u, "school": school, "tests": tests})
    tests = webdb.list_mcq_tests()
    return templates.TemplateResponse(request, "cbt_index.html", {
        "user": u, "school": school, "tests": tests, "presets": webdb.EXAM_PRESETS})


@app.get("/cbt/bank", response_class=HTMLResponse)
def cbt_bank(request: Request, exam_type: str = "school", added: int = 0):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    school = webdb.get_school_info()
    subjects = webdb.mcq_subjects(exam_type)
    counts = {subj: webdb.mcq_question_count(exam_type, subj) for subj in subjects}
    return templates.TemplateResponse(request, "cbt_bank.html", {
        "user": u, "school": school, "exam_type": exam_type, "presets": webdb.EXAM_PRESETS,
        "subjects": subjects, "counts": counts, "added": added})


@app.post("/cbt/bank")
async def cbt_bank_add(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    et = (f.get("exam_type") or "school").strip()
    webdb.add_mcq_question(et, (f.get("subject") or "").strip(),
        (f.get("question") or "").strip(), (f.get("option_a") or "").strip(),
        (f.get("option_b") or "").strip(), (f.get("option_c") or "").strip(),
        (f.get("option_d") or "").strip(), (f.get("answer") or "").strip(),
        (f.get("topic") or "").strip(), (f.get("year") or "").strip())
    return RedirectResponse(f"/cbt/bank?exam_type={et}&added=1", status_code=302)


@app.get("/cbt/new", response_class=HTMLResponse)
def cbt_new(request: Request, exam_type: str = "school"):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    school = webdb.get_school_info()
    classes = webdb.get_all_class_names()
    subjects = webdb.mcq_subjects(exam_type)
    academic_subjects = [s["name"] for s in webdb.get_subjects(included_only=True)]
    preset = webdb.EXAM_PRESETS.get(exam_type, webdb.EXAM_PRESETS["school"])
    return templates.TemplateResponse(request, "cbt_new.html", {
        "user": u, "school": school, "exam_type": exam_type, "preset": preset,
        "presets": webdb.EXAM_PRESETS, "classes": classes, "subjects": subjects,
        "academic_subjects": academic_subjects})


@app.post("/cbt/new")
async def cbt_new_save(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    et = (f.get("exam_type") or "school").strip()
    subjects = f.getlist("subjects") if hasattr(f, "getlist") else f.get("subjects")
    if isinstance(subjects, str): subjects=[subjects]
    subjects = [x for x in (subjects or []) if x]
    try: nps=int(f.get("n_per_subject") or 20)
    except ValueError: nps=20
    try: dur=int(f.get("duration_min") or 30)
    except ValueError: dur=30
    tid = webdb.create_mcq_test(
        (f.get("title") or "CBT").strip(), et, (f.get("class_level") or "").strip(),
        subjects, nps, dur, (f.get("link_target") or "none").strip(),
        (f.get("link_subject") or "").strip(), u.get("name") or u.get("username"))
    return RedirectResponse("/cbt", status_code=302)


@app.get("/cbt/{test_id}/take", response_class=HTMLResponse)
def cbt_take(request: Request, test_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if u["role"] != "student":
        return HTMLResponse("Only students take CBT.", status_code=403)
    conn = webdb.get_conn()
    row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
    conn.close()
    sid = row[0] if row else None
    test = webdb.get_mcq_test(test_id)
    if not test:
        return HTMLResponse("Test not found", status_code=404)
    attempt = webdb.start_mcq_attempt(test_id, sid)
    if attempt.get("status") == "done":
        return RedirectResponse(f"/cbt/result/{attempt['id']}", status_code=302)
    import json, datetime
    qids = json.loads(attempt["question_ids"] or "[]")
    questions = webdb.get_mcq_questions_by_ids(qids)
    started = datetime.datetime.fromisoformat(attempt["started_at"])
    remaining = max(0, int(test["duration_min"]*60 - (datetime.datetime.now()-started).total_seconds()))
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "cbt_take.html", {
        "user": u, "school": school, "test": test, "questions": questions,
        "attempt": attempt, "remaining": remaining})


@app.post("/cbt/{test_id}/submit")
async def cbt_submit(request: Request, test_id: int):
    u = require_login(request)
    if not u or u["role"] != "student":
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    attempt_id = int(f.get("attempt_id"))
    responses = {}
    for k in f.keys():
        if k.startswith("q_"):
            responses[k[2:]] = f.get(k)
    webdb.submit_mcq_attempt(attempt_id, responses)
    return RedirectResponse(f"/cbt/result/{attempt_id}", status_code=302)


@app.get("/cbt/result/{attempt_id}", response_class=HTMLResponse)
def cbt_result(request: Request, attempt_id: int):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    attempt = webdb.get_mcq_attempt(attempt_id)
    if not attempt:
        return HTMLResponse("Attempt not found", status_code=404)
    if u["role"] == "student":
        conn = webdb.get_conn()
        row = conn.execute("SELECT student_id FROM users WHERE id=?", (u["id"],)).fetchone()
        conn.close()
        if not row or row[0] != attempt["student_id"]:
            return HTMLResponse("You can only view your own result.", status_code=403)
    test = webdb.get_mcq_test(attempt["test_id"])
    # staff self-attempts use a negative student_id
    if attempt["student_id"] and attempt["student_id"] < 0:
        student = {"full_name": u.get("name") or "Staff (practice)"}
    else:
        student = webdb.get_student(attempt["student_id"])
    pct = round((attempt["score"]/attempt["total"]*100),1) if attempt.get("total") else 0
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "cbt_result.html", {
        "user": u, "school": school, "test": test, "attempt": attempt, "student": student, "pct": pct})


@app.get("/cbt/{test_id}/scores", response_class=HTMLResponse)
def cbt_scores(request: Request, test_id: int, pushed: str = ""):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    test = webdb.get_mcq_test(test_id)
    attempts = webdb.list_mcq_attempts_for_test(test_id)
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "cbt_scores.html", {
        "user": u, "school": school, "test": test, "attempts": attempts, "pushed": pushed})


@app.post("/cbt/push/{attempt_id}")
async def cbt_push(request: Request, attempt_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    ok, msg = webdb.push_mcq_to_scores(attempt_id)
    att = webdb.get_mcq_attempt(attempt_id)
    import urllib.parse as _up
    return RedirectResponse(f"/cbt/{att['test_id']}/scores?pushed={_up.quote(msg)}", status_code=302)


@app.post("/cbt/import")
async def cbt_import(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    summary = webdb.import_desktop_cbt()
    import urllib.parse as _up
    msg = (f"Imported - School:{summary['school']} JAMB:{summary['jamb']} "
           f"WAEC:{summary['waec']} NECO:{summary['neco']} (skipped {summary['skipped']} duplicates)")
    return RedirectResponse(f"/cbt/bank?exam_type=school&imported={_up.quote(msg)}", status_code=302)


# ============================================================
# Staff "Start CBT Exam" - chooser, preview, staff take
# ============================================================

@app.get("/start-cbt", response_class=HTMLResponse)
def start_cbt_chooser(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    tests = webdb.list_all_mcq_tests()
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "start_cbt.html", {
        "user": u, "school": school, "tests": tests, "presets": webdb.EXAM_PRESETS})


@app.get("/start-cbt/{test_id}/preview", response_class=HTMLResponse)
def start_cbt_preview(request: Request, test_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    test, qs = webdb.get_mcq_test_preview(test_id)
    if not test:
        return HTMLResponse("Test not found", status_code=404)
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "cbt_preview.html", {
        "user": u, "school": school, "test": test, "questions": qs})


@app.get("/start-cbt/{test_id}/take", response_class=HTMLResponse)
def start_cbt_take(request: Request, test_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    test = webdb.get_mcq_test(test_id)
    if not test:
        return HTMLResponse("Test not found", status_code=404)
    staff_key = u.get("username") or str(u.get("id"))
    attempt = webdb.start_staff_mcq_attempt(test_id, staff_key)
    import json, datetime
    qids = json.loads(attempt["question_ids"] or "[]")
    questions = webdb.get_mcq_questions_by_ids(qids)
    started = datetime.datetime.fromisoformat(attempt["started_at"])
    remaining = max(0, int(test["duration_min"]*60 - (datetime.datetime.now()-started).total_seconds()))
    school = webdb.get_school_info()
    # reuse the student take template but post to the staff submit route
    return templates.TemplateResponse(request, "cbt_take.html", {
        "user": u, "school": school, "test": test, "questions": questions,
        "attempt": attempt, "remaining": remaining, "staff_take": True})


@app.post("/start-cbt/{test_id}/submit")
async def start_cbt_submit(request: Request, test_id: int):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    attempt_id = int(f.get("attempt_id"))
    responses = {}
    for k in f.keys():
        if k.startswith("q_"):
            responses[k[2:]] = f.get(k)
    webdb.submit_mcq_attempt(attempt_id, responses)
    return RedirectResponse(f"/cbt/result/{attempt_id}", status_code=302)


# ============================================================
# PHASE 7 - AI question generator (local, scheme-driven)
# ============================================================

@app.get("/generate", response_class=HTMLResponse)
def generate_form(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Only staff.", status_code=403)
    school = webdb.get_school_info()
    subjects = webdb.mcq_subjects()
    return templates.TemplateResponse(request, "generate.html", {
        "user": u, "school": school, "presets": webdb.EXAM_PRESETS,
        "subjects": subjects, "results": None, "form": {}})


@app.post("/generate", response_class=HTMLResponse)
async def generate_run(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    exam_type = (f.get("exam_type") or "school").strip()
    subject = (f.get("subject") or "").strip()
    scheme = (f.get("scheme") or "").strip()
    try: mcq_per = int(f.get("mcq_per") or 5)
    except ValueError: mcq_per = 5
    try: theory_per = int(f.get("theory_per") or 2)
    except ValueError: theory_per = 2
    results = webdb.generate_from_scheme(exam_type, subject, scheme, mcq_per, theory_per)
    school = webdb.get_school_info()
    subjects = webdb.mcq_subjects()
    return templates.TemplateResponse(request, "generate.html", {
        "user": u, "school": school, "presets": webdb.EXAM_PRESETS, "subjects": subjects,
        "results": results, "form": {"exam_type": exam_type, "subject": subject,
                                     "scheme": scheme, "mcq_per": mcq_per, "theory_per": theory_per}})


@app.post("/generate/save")
async def generate_save(request: Request):
    u = require_login(request)
    if not u or not _teacher(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    exam_type = (f.get("exam_type") or "school").strip()
    subject = (f.get("subject") or "").strip()
    saved_mcq = 0
    saved_theory = 0
    # MCQ: fields mq_<i>_question, mq_<i>_a..d, mq_<i>_answer, mq_<i>_topic, keep_mq_<i>
    idx = 0
    while True:
        qk = f.get(f"mq_{idx}_question")
        if qk is None:
            break
        if f.get(f"keep_mq_{idx}"):
            webdb.add_mcq_question(exam_type, subject, qk.strip(),
                f.get(f"mq_{idx}_a","" ).strip(), f.get(f"mq_{idx}_b","").strip(),
                f.get(f"mq_{idx}_c","").strip(), f.get(f"mq_{idx}_d","").strip(),
                f.get(f"mq_{idx}_answer","").strip(), f.get(f"mq_{idx}_topic","").strip())
            saved_mcq += 1
        idx += 1
    # store theory into a generated theory exam if any kept
    keep_theory = []
    idx = 0
    while True:
        tk = f.get(f"tq_{idx}_question")
        if tk is None:
            break
        if f.get(f"keep_tq_{idx}"):
            try: mk = float(f.get(f"tq_{idx}_marks") or 5)
            except ValueError: mk = 5
            keep_theory.append((tk.strip(), mk, f.get(f"tq_{idx}_model","").strip()))
        idx += 1
    if keep_theory:
        eid = webdb.create_theory_exam(
            f"Generated Theory - {subject}", subject, "", 60,
            "Generated from scheme of work.", "type", u.get("name") or u.get("username"))
        for q, mk, model in keep_theory:
            webdb.add_theory_question(eid, q, mk, model)
        saved_theory = len(keep_theory)
    import urllib.parse as _up
    msg = f"Saved {saved_mcq} MCQ to the {exam_type} bank" + (f" and {saved_theory} theory questions into a new theory exam." if saved_theory else ".")
    return RedirectResponse(f"/cbt/bank?exam_type={exam_type}&imported={_up.quote(msg)}", status_code=302)


# ============================================================
# PHASE 8a - Debtors & Arrears (admin/bursar)
# ============================================================

@app.get("/debtors", response_class=HTMLResponse)
def debtors(request: Request, class_level: str = "All", q: str = ""):
    u = require_login(request)
    if not u:
        return RedirectResponse("/login", status_code=302)
    if not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar can view debtors.", status_code=403)
    data = webdb.get_debtors_overview(class_level=(None if class_level=="All" else class_level), search=q or None)
    school = webdb.get_school_info()
    # attach a whatsapp link per row
    for r in data["rows"]:
        r["wa"] = webdb.debtor_whatsapp(r, school)
    classes = ["All"] + webdb.get_all_class_names()
    return templates.TemplateResponse(request, "debtors.html", {
        "user": u, "school": school, "data": data, "classes": classes,
        "selected_class": class_level, "search": q, "naira": webdb.naira})


# ============================================================
# PHASE 8b/8c - Expenses + Accounts (admin/bursar)
# ============================================================

@app.get("/expenses", response_class=HTMLResponse)
def expenses_page(request: Request, category: str = "All", saved: int = 0):
    u = require_login(request)
    if not u or not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar.", status_code=403)
    rows = webdb.list_expenses(term_only=True, category=category)
    total = webdb.expenses_total(True)
    by_cat = webdb.expenses_by_category(True)
    school = webdb.get_school_info()
    from datetime import date as _date
    return templates.TemplateResponse(request, "expenses.html", {
        "user": u, "school": school, "rows": rows, "total": total, "by_cat": by_cat,
        "categories": webdb.get_expense_categories(), "selected": category, "naira": webdb.naira,
        "today": _date.today().isoformat(), "saved": saved})


@app.post("/expenses")
async def expenses_add(request: Request):
    u = require_login(request)
    if not u or not _fees_allowed(u):
        return HTMLResponse("Not allowed", status_code=403)
    f = await request.form()
    from datetime import date as _date
    try:
        amount = float((f.get("amount") or "0").strip())
    except ValueError:
        amount = 0
    if amount > 0:
        webdb.add_expense(
            (f.get("expense_date") or _date.today().isoformat()).strip(),
            (f.get("category") or "Others").strip(), (f.get("title") or "").strip(),
            amount, (f.get("vendor") or "").strip(), (f.get("payment_method") or "Cash").strip(),
            u.get("name") or u.get("username"),
            note=(f.get("note") or "").strip(), receipt_no=(f.get("receipt_no") or "").strip())
    return RedirectResponse("/expenses?saved=1", status_code=302)


@app.post("/expenses/{expense_id}/delete")
async def expenses_delete(request: Request, expense_id: int):
    u = require_login(request)
    if not u or not _fees_allowed(u):
        return HTMLResponse("Not allowed", status_code=403)
    webdb.delete_expense(expense_id)
    return RedirectResponse("/expenses", status_code=302)


@app.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request):
    u = require_login(request)
    if not u or not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar.", status_code=403)
    summary = webdb.get_accounts_summary(term_only=True)
    school = webdb.get_school_info()
    return templates.TemplateResponse(request, "accounts.html", {
        "user": u, "school": school, "s": summary, "naira": webdb.naira})


@app.get("/accounts/report.pdf")
def accounts_pdf(request: Request):
    u = require_login(request)
    if not u or not _fees_allowed(u):
        return HTMLResponse("Only admin or bursar.", status_code=403)
    summary = webdb.get_accounts_summary(term_only=True)
    school = webdb.get_school_info()
    import pdfgen, os
    logo_path = None
    for cand in ("logo.png","logo.jpg","logo.jpeg"):
        p = os.path.join(BASE,"static",cand)
        if os.path.exists(p): logo_path=p; break
    if not logo_path:
        lp = school.get("logo_path")
        if lp and os.path.exists(lp):
            logo_path = lp
    buf = pdfgen.accounts_report(summary, school, logo_path=logo_path)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=Financial_Report.pdf"})


@app.get("/school-logo")
def school_logo(request: Request):
    """Serve the school logo: prefer static/logo.png, else the logo_path from setup."""
    import os
    from fastapi.responses import FileResponse
    # 1) static/logo.png (or jpg)
    for cand in ("logo.png","logo.jpg","logo.jpeg"):
        p = os.path.join(BASE,"static",cand)
        if os.path.exists(p):
            return FileResponse(p)
    # 2) logo_path stored in school_info (desktop logo location)
    info = webdb.get_school_info()
    lp = info.get("logo_path")
    if lp and os.path.exists(lp):
        return FileResponse(lp)
    return HTMLResponse("", status_code=404)
