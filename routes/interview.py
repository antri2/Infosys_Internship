"""
Interview Preparation: static Q&A content for now. No DB dependency --
straightforward to later swap for DB-backed or AI-generated content
without changing the route's contract (still renders `categories`).
"""
from flask import Blueprint, render_template, redirect, url_for, session

interview_bp = Blueprint("interview", __name__, url_prefix="/interview")


def _require_login():
    return "user_id" in session


CATEGORIES = [
    {
        "name": "Technical",
        "icon": "💻",
        "questions": [
            ("What is the difference between a list and a tuple in Python?",
             "Lists are mutable and defined with [], tuples are immutable and defined with (). "
             "Tuples are generally faster and used for fixed collections of data."),
            ("Explain the difference between SQL JOIN types.",
             "INNER JOIN returns matching rows only; LEFT JOIN keeps all rows from the left table; "
             "RIGHT JOIN keeps all rows from the right table; FULL JOIN keeps all rows from both."),
            ("What is REST, and what makes an API RESTful?",
             "REST is an architectural style for APIs using stateless requests over HTTP, resource-based "
             "URLs, and standard verbs (GET/POST/PUT/DELETE) to operate on those resources."),
            ("What's the difference between == and === in JavaScript?",
             "== compares values after type coercion; === compares both value and type without coercion."),
        ],
    },
    {
        "name": "HR",
        "icon": "🧑\u200d💼",
        "questions": [
            ("Tell me about yourself.",
             "Keep it to 60-90 seconds: current status, 2-3 relevant skills/experiences, and why you're "
             "interested in this specific role."),
            ("Why do you want to work here?",
             "Show you've researched the company: mention something specific about their product, "
             "mission, or team, and connect it to your own goals."),
            ("What are your strengths and weaknesses?",
             "Pick a real weakness and show what you're doing to improve it -- avoid disguised "
             "strengths like 'I work too hard'."),
            ("Where do you see yourself in five years?",
             "Focus on growth within the field/industry rather than a specific job title -- shows "
             "ambition without sounding like you'll leave immediately."),
        ],
    },
    {
        "name": "Coding",
        "icon": "🧩",
        "questions": [
            ("Reverse a string without using built-in reverse functions.",
             "Iterate from the last character to the first, building a new string (or use two-pointer "
             "swap if working in-place on a mutable structure like a list of characters)."),
            ("Find duplicates in an array.",
             "Use a hash set: iterate once, add each element, and if an element is already in the set, "
             "it's a duplicate. O(n) time, O(n) space."),
            ("What is time complexity, and why does it matter?",
             "It describes how an algorithm's runtime grows with input size (e.g. O(n), O(log n), O(n^2)) "
             "-- critical for knowing whether code will scale."),
            ("Explain recursion with an example.",
             "A function that calls itself with a smaller input until it hits a base case -- e.g. "
             "factorial(n) = n * factorial(n-1), with factorial(0) = 1 as the base case."),
        ],
    },
    {
        "name": "Aptitude",
        "icon": "🧮",
        "questions": [
            ("If a train travels 60 km in 45 minutes, what is its speed in km/h?",
             "Speed = distance / time = 60 km / 0.75 h = 80 km/h."),
            ("A shopkeeper marks up an item by 25% then gives a 20% discount. Profit or loss?",
             "125 * 0.8 = 100 -- exactly break-even (0% profit/loss) on the original cost."),
            ("Complete the series: 2, 6, 12, 20, 30, ?",
             "Differences are 4, 6, 8, 10, 12 -- next term is 30 + 12 = 42."),
            ("If 5 workers can build a wall in 10 days, how long will 10 workers take?",
             "Work is constant: 5 * 10 = 50 worker-days. 50 / 10 workers = 5 days."),
        ],
    },
]


@interview_bp.route("/", methods=["GET"])
def view():
    if not _require_login():
        return redirect(url_for("auth.login"))
    return render_template("interview.html", active_page="interview", categories=CATEGORIES)