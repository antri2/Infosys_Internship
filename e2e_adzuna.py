"""End-to-end verification of the live Adzuna source (TEST 1-12).

Runs against the real API with the real credentials from .env.
"""
import os
import re
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8")
os.environ["CAREERAI_TEST_DATABASE"] = "career_ai_step1_test"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


from database.db import get_db
from services import adzuna_service, live_job_store, opportunity_service
from services.job_matcher import compute_match
from app import create_app

app = create_app()
app.config.update(TESTING=True)

print("=" * 78)
print("TEST 1  direct Adzuna search")
jobs = adzuna_service.search_jobs("data analyst", location="India", results_per_page=3)
# Adzuna's index drifts, so assert we got usable jobs rather than an exact count.
check("TEST 1 returns usable Adzuna jobs", len(jobs) >= 1, f"got {len(jobs)}")
if jobs:
    j = jobs[0]
    print(f"        e.g. {j['job_id']} | {j['title'][:38]} | {j['company'][:20]} | {j['source']}")
    check("TEST 1 source == adzuna", j["source"] == "adzuna")
    check("TEST 1 job_type is a real type", "live" not in j["job_type"].lower(), repr(j["job_type"]))

print()
print("=" * 78)
print("TEST 2  recommendation service")
rec = opportunity_service.recommend_jobs("data analyst", [], top_k=3)
check("TEST 2 returns jobs", len(rec) >= 1, f"got {len(rec)}")
check("TEST 2 source == adzuna", all(r.get("source") == "adzuna" for r in rec))

# ---------------------------------------------------------------- fixtures
with app.app_context():
    db = get_db()
    with db.cursor() as c:
        marker = uuid.uuid4().hex[:8]
        c.execute(
            "INSERT INTO users (name,email,phone,password_hash,career_status) "
            "VALUES (%s,%s,%s,'x','Fresher')",
            (f"E2E {marker}", f"e2e-{marker}@example.test", "+91 90000 00000"),
        )
        uid = c.lastrowid
        c.execute(
            "INSERT INTO resumes (user_id,file_path,file_type,parse_status) VALUES (%s,%s,'pdf','parsed')",
            (uid, f"t/{marker}.pdf"),
        )
        rid = c.lastrowid
        c.execute(
            "INSERT INTO education (user_id,institution,degree) VALUES (%s,'X','B.Tech')", (uid,)
        )
        c.execute(
            "INSERT INTO profiles (user_id,resume_id,college,degree,cgpa) VALUES (%s,%s,'X','B.Tech',8.5)",
            (uid, rid),
        )
        for n in ("Python", "SQL", "Excel"):
            c.execute("INSERT INTO skills (user_id,name,category) VALUES (%s,%s,'tool')", (uid, n))
    db.commit()

client = app.test_client()
with client.session_transaction() as s:
    s["user_id"] = uid
    s["user_name"] = f"E2E {marker}"

print()
print("=" * 78)
print("TEST 3  Opportunities with NO search")
r = client.get("/opportunities/")
h = r.get_data(as_text=True)
cards = re.findall(r'<div class="opportunity-card">(.*?)</div>\s*</div>', h, re.S)
titles = re.findall(r'class="opportunity-title">([^<]+)</', h)
check("TEST 3 page renders", r.status_code == 200)
check("TEST 3 shows opportunities without searching", len(titles) > 0, f"{len(titles)} jobs")
print(f"        first 3: {[t[:34] for t in titles[:3]]}")

print()
print("=" * 78)
print("TEST 4  search 'data analyst'")
h4 = client.get("/opportunities/?q=data+analyst").get_data(as_text=True)
t4 = re.findall(r'class="opportunity-title">([^<]+)</', h4)
check("TEST 4 returns jobs", len(t4) > 0, f"{len(t4)} jobs")
print(f"        first 3: {[t[:34] for t in t4[:3]]}")

print()
print("=" * 78)
print("TEST 5  search 'python developer'")
h5 = client.get("/opportunities/?q=python+developer").get_data(as_text=True)
t5 = re.findall(r'class="opportunity-title">([^<]+)</', h5)
check("TEST 5 results differ from TEST 4", set(t5) != set(t4), f"{len(t5)} jobs")
print(f"        first 3: {[t[:34] for t in t5[:3]]}")

print()
print("=" * 78)
print("TEST 6  skill matching on a live job")
live = [t for t in t4]
target = None
for raw in adzuna_service.search_jobs("data analyst", location="India", results_per_page=5):
    m = compute_match(["Python", "SQL", "Excel"], raw)
    if m["match_available"]:
        target = raw
        break
if target:
    m = compute_match(["Python", "SQL", "Excel"], target)
    print(f"        job      : {target['title'][:44]}")
    print(f"        required : {target['required_skills'][:70]}")
    print(f"        preferred: {target['preferred_skills'][:70]}")
    print(f"        matched  : {m['matched_skills']}  missing: {m['missing_skills']}")
    print(f"        fit      : {m['match_percent']}%")
    check("TEST 6 matched/missing calculated", isinstance(m["match_percent"], int))
else:
    check("TEST 6 found a live job with extractable skills", False, "none in sample")

print()
print("=" * 78)
print("TEST 7/8/9/10  per-job features on a live job")
# refresh the live cache then pick a job that has real requirements
picked = None
for raw in adzuna_service.search_jobs("data analyst", location="India", results_per_page=8):
    if raw["required_skills"]:
        picked = raw
        break
picked = picked or (jobs[0] if jobs else None)

if picked:
    jid = picked["job_id"]
    print(f"        using job {jid}: {picked['title'][:44]}")
    title_q = picked["title"].replace(" ", "+")

    r7 = client.get(f"/skill-gap/?job_id={jid}&target_role={title_q}")
    h7 = r7.get_data(as_text=True)
    check("TEST 7 Skill Gap page loads for a live job", r7.status_code == 200 and "not found" not in h7)
    print(f"        skill-gap status={r7.status_code}")

    r8 = client.post(f"/opportunities/{jid}/ai-summary")
    body8 = r8.get_json() if r8.is_json else {}
    ok8 = r8.status_code == 200 and bool(body8.get("summary"))
    check("TEST 8 AI Summary works for a live job", ok8,
          f"status={r8.status_code} {str(body8.get('summary'))[:70] if body8 else ''}")
    if not ok8:
        print(f"        AI summary response: {str(body8)[:160]}")

    r9 = client.get(f"/interview/?job_id={jid}&target_role={title_q}&target_source=custom")
    check("TEST 9 Prepare for Interview works", r9.status_code == 200)
    print(f"        interview status={r9.status_code}")

    rs = client.post(f"/applications/{jid}/save")
    bs = rs.get_json() if rs.is_json else {}
    # 201 when a new application row is created, 200 when it already existed --
    # both are the pre-existing REST behaviour of this endpoint.
    check("TEST 10 Save a live job", rs.status_code in (200, 201),
          f"status={rs.status_code} created={bs.get('created')}")
    ra = client.post(f"/applications/{jid}/apply")
    ba = ra.get_json() if ra.is_json else {}
    check("TEST 10 Apply a live job", ra.status_code in (200, 201),
          f"status={ra.status_code} state={ba.get('status')}")

    with app.app_context():
        db = get_db()
        with db.cursor() as c:
            c.execute(
                "SELECT a.status, j.title FROM applications a JOIN jobs j ON j.job_id=a.job_id "
                "WHERE a.user_id=%s AND a.job_id=%s",
                (uid, jid),
            )
            row = c.fetchone()
    print(f"        applications row: {dict(row) if row else None}")
    check("TEST 10 tracked with readable title", bool(row and row["title"]))
else:
    check("TEST 7-10 a live job was available", False)

print()
print("=" * 78)
print("TEST 11  fallback when Adzuna is unavailable")
import config

saved = config.ADZUNA_ENABLED
config.ADZUNA_ENABLED = False
try:
    local = opportunity_service.recommend_jobs("machine learning", ["Python", "SQL"], top_k=10)
    check("TEST 11 local FAISS jobs returned", len(local) > 0, f"{len(local)} jobs")
    check("TEST 11 all local source", all(r.get("source") == "local" for r in local))
    hl = client.get("/opportunities/?q=machine+learning").get_data(as_text=True)
    tl = re.findall(r'class="opportunity-title">([^<]+)</', hl)
    check("TEST 11 Opportunities page still renders", len(tl) > 0, f"{len(tl)} jobs")
    print(f"        first 3 local: {[t[:34] for t in tl[:3]]}")
finally:
    config.ADZUNA_ENABLED = saved

print()
print("=" * 78)
print("TEST 12  brand new user, no skills")
with app.app_context():
    db = get_db()
    with db.cursor() as c:
        m2 = uuid.uuid4().hex[:8]
        c.execute(
            "INSERT INTO users (name,email,phone,password_hash,career_status) "
            "VALUES (%s,%s,%s,'x','Fresher')",
            (f"New {m2}", f"new-{m2}@example.test", "+91 91111 11111"),
        )
        uid2 = c.lastrowid
        c.execute(
            "INSERT INTO resumes (user_id,file_path,file_type,parse_status) VALUES (%s,%s,'pdf','parsed')",
            (uid2, f"t/{m2}.pdf"),
        )
        rid2 = c.lastrowid
        c.execute("INSERT INTO profiles (user_id,resume_id) VALUES (%s,%s)", (uid2, rid2))
    db.commit()

c2 = app.test_client()
with c2.session_transaction() as s:
    s["user_id"] = uid2
    s["user_name"] = f"New {m2}"
r12 = c2.get("/opportunities/")
t12 = re.findall(r'class="opportunity-title">([^<]+)</', r12.get_data(as_text=True))
check("TEST 12 new user sees opportunities", r12.status_code == 200 and len(t12) > 0, f"{len(t12)} jobs")
print(f"        first 3: {[t[:34] for t in t12[:3]]}")

print()
print("=" * 78)
print("REQUIREMENT 5  no 'Live' wording anywhere on the card")
for name, html in (("no-search", h), ("data analyst", h4), ("python", h5)):
    main = re.search(r"<main class=\"app-main\">(.*)</main>", html, re.S)
    body = main.group(1) if main else ""
    bad = [w for w in (">Live<", "Live listing", "Live Job", "Adzuna Live") if w in body]
    check(f"no '{name}' page shows Live wording", not bad, str(bad))

print()
print("=" * 78)
with app.app_context():
    db = get_db()
    with db.cursor() as c:
        c.execute("DELETE FROM users WHERE id IN (%s,%s)", (uid, uid2))
    db.commit()
live_job_store.clear()

passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"RESULT: {passed}/{len(RESULTS)} checks passed")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} {detail}")
