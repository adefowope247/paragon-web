"""
Build a RICH demo database for the public live demo so clients can navigate
every feature with realistic data. Run: python build_demo.py
Creates school_data.db fresh (deletes any existing one).
"""
import os, sqlite3, hashlib, datetime, random

DB = os.environ.get("PARAGON_DB", "school_data.db")

def h(pw): return hashlib.sha256(pw.encode()).hexdigest()

# On a server we only build the demo ONCE; if the DB already exists, keep it
# (so data survives restarts on the persistent disk). Delete to force a rebuild.
if os.path.exists(DB):
    print("DB already exists at", DB, "- keeping it. Delete the file to rebuild the demo.")
    raise SystemExit(0)

import webdb
webdb.ensure_demo_db()   # lay down base schema + a few rows
conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
c = conn.cursor()

# ---- school details ----
for col in ["address","phone","email","motto","website","logo_path","principal_name","principal_title"]:
    try: c.execute(f"ALTER TABLE school_info ADD COLUMN {col} TEXT")
    except Exception: pass
c.execute("""UPDATE school_info SET
    name='ABC Group of Schools (DEMO)',
    address='15 Demo Avenue, Sample Town, Demo State',
    phone='0800 000 0000',
    email='info@abcschools.demo',
    motto='Learning for Life',
    website='www.abcschools.demo',
    principal_name='Mr. John Demo', principal_title='Head Teacher',
    session='2025/2026', term='3rd' WHERE id=1""")

# ---- subjects: add a few more ----
existing_sub = [r[0] for r in c.execute("SELECT name FROM subjects").fetchall()]
extra_subs = ["Quranic Studies","Social Studies","Civic Education","Verbal Reasoning","Quantitative Reasoning"]
order = len(existing_sub)
for s in extra_subs:
    if s not in existing_sub:
        order += 1
        c.execute("INSERT INTO subjects (name,sort_order,included) VALUES (?,?,1)", (s, order))
subjects = c.execute("SELECT id,name FROM subjects WHERE included=1 ORDER BY sort_order").fetchall()
subj_ids = [r[0] for r in subjects]

# ---- more students across classes ----
classes = ["Primary 1","Primary 2","Primary 3","Primary 4","Primary 5"]
first = ["Aisha","Ibrahim","Fatima","Yusuf","Khadija","Musa","Zainab","Umar","Maryam","Bilal",
         "Halima","Suleiman","Aminat","Tijani","Ruqayyah","Abdullahi","Safiya","Hamza","Habiba","Nasir"]
last = ["Adeyemi","Bello","Okonkwo","Lawal","Ahmed","Salami","Yakubu","Ogunlana","Danjuma","Oyelaran"]
# keep the existing demo students; add ~24 more
existing_count = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
adm = 100
random.seed(42)
for i in range(24):
    fn = f"{random.choice(first)} {random.choice(last)}"
    cls = random.choice(classes)
    g = random.choice(["M","F"])
    adm += 1
    phone = f"080{random.randint(30000000,39999999)}"
    c.execute("INSERT INTO students (full_name,admission_no,gender,class_level,parent_phone,parent_name,active) VALUES (?,?,?,?,?,?,1)",
              (fn, f"PS/2025/{adm:03d}", g, cls, phone, "Parent/Guardian"))

# student logins for a couple so demo visitors can log in as a student
c.execute("SELECT id,admission_no,full_name FROM students WHERE active=1")
all_students = c.fetchall()

# ---- class_subjects: assign all included subjects to all classes ----
for cls in classes:
    for sid in subj_ids:
        c.execute("INSERT INTO class_subjects (class_name,subject_id) VALUES (?,?)", (cls, sid))

# ---- scores: give every student full scores in their class subjects ----
for st in all_students:
    sid = st["id"]
    # skip if already has scores
    has = c.execute("SELECT COUNT(*) FROM scores WHERE student_id=?", (sid,)).fetchone()[0]
    if has: continue
    for subj_id in subj_ids:
        ca1 = random.randint(8,20); ca2 = random.randint(8,20); exam = random.randint(25,60)
        c.execute("INSERT INTO scores (student_id,subject_id,ca1,ca2,exam) VALUES (?,?,?,?,?)",
                  (sid, subj_id, ca1, ca2, exam))

# ---- fees: structures for all classes, this term + previous (for arrears) ----
fee_amounts = {"Primary 1":15000,"Primary 2":18000,"Primary 3":20000,"Primary 4":22000,"Primary 5":24000}
for cls, amt in fee_amounts.items():
    for term in ["1st","2nd","3rd"]:
        c.execute("INSERT INTO fee_structures (name,class_level,session,term,amount,category,active) VALUES (?,?,?,?,?,?,1)",
                  ("Tuition", cls, "2025/2026", term, amt, "Tuition"))
# payments: random mix so we have payers, part-payers, debtors, and arrears
for st in all_students:
    sid = st["id"]; cls = c.execute("SELECT class_level FROM students WHERE id=?", (sid,)).fetchone()[0]
    amt = fee_amounts.get(cls, 15000)
    # 1st & 2nd term: most fully paid, some leave arrears
    for term in ["1st","2nd"]:
        if random.random() < 0.8:
            c.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (?,?,?,?,?,?,?,?)",
                      (sid, amt, "2025-10-01", "Transfer", f"R{sid}{term}", "2025/2026", term, "admin"))
        elif random.random() < 0.5:
            c.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (?,?,?,?,?,?,?,?)",
                      (sid, amt*0.5, "2025-10-01", "Cash", f"R{sid}{term}p", "2025/2026", term, "admin"))
    # 3rd (current) term: varied
    r = random.random()
    if r < 0.4:
        c.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (?,?,?,?,?,?,?,?)",
                  (sid, amt, "2026-01-15", "Transfer", f"R{sid}3", "2025/2026", "3rd", "admin"))
    elif r < 0.7:
        c.execute("INSERT INTO fee_payments (student_id,amount_paid,payment_date,payment_method,receipt_no,session,term,recorded_by) VALUES (?,?,?,?,?,?,?,?)",
                  (sid, amt*0.5, "2026-01-20", "Cash", f"R{sid}3p", "2025/2026", "3rd", "admin"))
    # else: no payment this term (debtor)

# ---- expenses (real desktop schema) ----
c.executescript("""
CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, amount REAL, category TEXT,
    expense_date TEXT, session TEXT, term TEXT, payment_method TEXT, vendor TEXT, receipt_no TEXT, recorded_by TEXT, note TEXT, receipt_file TEXT);
CREATE TABLE IF NOT EXISTS expense_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, sort_order INTEGER, active INTEGER DEFAULT 1);
""")
for i,nm in enumerate(["Staff Salaries","Teaching Materials","Electricity","Diesel/Fuel","Maintenance","Feeding"]):
    c.execute("INSERT INTO expense_categories (name,sort_order,active) VALUES (?,?,1)", (nm, i))
demo_exp = [
    ("May staff salaries", 320000, "Staff Salaries", "2026-05-28", "Transfer", "Payroll"),
    ("Exercise books & charts", 45000, "Teaching Materials", "2026-05-10", "Cash", "Ede Bookshop"),
    ("Diesel for generator", 60000, "Diesel/Fuel", "2026-05-18", "Cash", "Total Filling Station"),
    ("NEPA electricity bill", 28000, "Electricity", "2026-05-05", "Transfer", "IBEDC"),
    ("Classroom repairs", 35000, "Maintenance", "2026-05-22", "Cash", "Local contractor"),
]
for t,a,cat,d,m,v in demo_exp:
    c.execute("INSERT INTO expenses (title,amount,category,expense_date,session,term,payment_method,vendor,recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
              (t,a,cat,d,"2025/2026","3rd",m,v,"admin"))

# ---- MCQ: a few more + a ready-made test ----
more_mcq = [
    ("school","Basic Science","Which organ pumps blood?","Liver","Heart","Lung","Kidney","B"),
    ("school","Basic Science","Water boils at how many degrees Celsius?","50","75","100","120","C"),
    ("school","Social Studies","The head of a local government is the?","Governor","Chairman","President","King","B"),
    ("waec","Mathematics","Solve: 15 - 6 + 2","11","9","13","7","A"),
    ("waec","English Language","Pick the noun: 'She runs fast.'","She","runs","fast","none","A"),
    ("neco","Mathematics","What is 12 / 4?","2","3","4","6","B"),
]
for et,subj,q,a,b,cc,d,ans in more_mcq:
    c.execute("INSERT INTO mcq_questions (exam_type,subject,question,option_a,option_b,option_c,option_d,answer,active) VALUES (?,?,?,?,?,?,?,?,1)",
              (et,subj,q,a,b,cc,d,ans))

# ---- DEFAULT DEMO LOGINS (admin / staff / student) ----
# admin: created by ensure_demo_db as admin/admin123 - keep, tidy display name
c.execute("UPDATE users SET display_name='Demo Administrator' WHERE username='admin'")

# staff/teacher login -> role 'teacher' (grants staff access). Link to a staff row.
c.execute("INSERT INTO staff (full_name,staff_no,status) VALUES (?,?,?)", ("Demo Teacher","STF/DEMO","Active"))
_staff_id = c.lastrowid
c.execute("DELETE FROM users WHERE username='teacher'")
c.execute("INSERT INTO users (username,password_hash,role,display_name,staff_id,active) VALUES (?,?,?,?,?,1)",
          ("teacher", h("teacher123"), "teacher", "Demo Teacher", _staff_id))

# student login -> pick the first demo student, give a memorable login 'student'/'student123'
_first_student = c.execute("SELECT id, full_name FROM students ORDER BY id LIMIT 1").fetchone()
c.execute("DELETE FROM users WHERE username='student'")
c.execute("INSERT INTO users (username,password_hash,role,display_name,student_id,active) VALUES (?,?,?,?,?,1)",
          ("student", h("student123"), "student", _first_student["full_name"], _first_student["id"]))

conn.commit(); conn.close()

# ---- create a CBT test + a theory exam via webdb so tables init properly ----
webdb.create_mcq_test("Sample School Test - Maths & English","school","Primary 1",
                      ["Mathematics","English Language"], 3, 20, "none", "", "admin")
eid = webdb.create_theory_exam("Third Term English Theory (Sample)","English Language","Primary 1",
                               45, "Answer ALL questions.", "type", "admin")
webdb.add_theory_question(eid, "Write a short letter to your friend telling them about your school. (Begin with a greeting.)", 10,
                          "Greeting, body describing school, closing.")
webdb.add_theory_question(eid, "Use the word 'because' in a correct sentence.", 5, "Any correct usage.")
webdb.add_theory_question(eid, "Name three things you can find in a classroom.", 6, "e.g. chair, table, board.")

print("Rich demo database built:", DB)
# quick counts
conn = sqlite3.connect(DB)
for tbl in ["students","scores","fee_payments","expenses","mcq_questions","theory_questions"]:
    try: print(f"  {tbl}: {conn.execute('SELECT COUNT(*) FROM '+tbl).fetchone()[0]}")
    except Exception as e: print(f"  {tbl}: (n/a)")
conn.close()
