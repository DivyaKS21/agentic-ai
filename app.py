
from flask import Flask, render_template, request, redirect, url_for, session
import fitz
import os
import re
import random

app = Flask(__name__)
app.secret_key = "quizforge_local_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

extracted_content = []
generated_questions = []

DIFFICULTY_LEVELS = {
    "Easy": 1,
    "Medium": 2,
    "Hard": 3
}


# --------------------------------
# TOPIC CLASSIFICATION
# --------------------------------

def identify_topic(sentence):

    text = sentence.lower()

    topics = {
        "DBMS": [
            "database", "sql", "table", "query",
            "normalization", "primary key", "foreign key",
            "relation", "tuple", "attribute"
        ],

        "Operating Systems": [
            "operating system", "process", "memory",
            "scheduling", "thread", "kernel", "paging"
        ],

        "Computer Networks": [
            "network", "protocol", "router", "tcp",
            "ip address", "transmission", "packet"
        ],

        "Programming": [
            "program", "function", "variable", "python",
            "algorithm", "compiler", "code"
        ]
    }

    for topic, keywords in topics.items():

        if any(keyword in text for keyword in keywords):
            return topic

    return "General"


# --------------------------------
# DIFFICULTY CLASSIFICATION
# --------------------------------

def classify_difficulty(sentence):

    words = sentence.split()

    long_words = [
        word for word in words
        if len(word.strip(".,:;()[]{}")) >= 9
    ]

    if len(words) >= 20 or len(long_words) >= 4:
        return "Hard"

    elif len(words) >= 13 or len(long_words) >= 2:
        return "Medium"

    return "Easy"


# --------------------------------
# GENERATE QUESTIONS
# --------------------------------

def generate_questions(content):

    questions = []

    for item in content:

        sentences = re.split(
            r'(?<=[.!?])\s+',
            item["content"]
        )

        for sentence in sentences:

            sentence = sentence.strip()
            words = sentence.split()

            if len(words) < 7 or len(words) > 40:
                continue

            candidates = [
                word.strip(".,:;()[]{}")
                for word in words
                if len(word.strip(".,:;()[]{}")) > 4
                and word.strip(".,:;()[]{}").isalpha()
            ]

            if not candidates:
                continue

            answer = candidates[len(candidates) // 2]

            if answer.lower() in [
                "which", "these", "those", "there",
                "where", "their", "about"
            ]:
                continue

            blank_sentence = sentence.replace(
                answer, "________", 1
            )

            options = [answer]

            for word in candidates:

                if word.lower() not in [
                    option.lower() for option in options
                ]:
                    options.append(word)

                if len(options) == 4:
                    break

            if len(options) < 4:
                continue

            random.shuffle(options)

            questions.append({

                "question": blank_sentence,
                "options": options,
                "answer": answer,
                "page": item["page"],
                "difficulty": classify_difficulty(sentence),
                "topic": identify_topic(sentence)

            })

    return questions


# --------------------------------
# SELECT NEXT ADAPTIVE QUESTION
# --------------------------------

def select_next_question(target_level):

    used = session.get("used_indices", [])

    available = [
        index for index in range(len(generated_questions))
        if index not in used
    ]

    if not available:
        return None

    # Prefer the target difficulty.
    # If unavailable, select the nearest available level.

    available.sort(
        key=lambda index: abs(
            DIFFICULTY_LEVELS[
                generated_questions[index]["difficulty"]
            ] - target_level
        )
    )

    best_distance = abs(
        DIFFICULTY_LEVELS[
            generated_questions[available[0]]["difficulty"]
        ] - target_level
    )

    best_questions = [
        index for index in available
        if abs(
            DIFFICULTY_LEVELS[
                generated_questions[index]["difficulty"]
            ] - target_level
        ) == best_distance
    ]

    return random.choice(best_questions)


# --------------------------------
# HOME DASHBOARD
# --------------------------------

@app.route("/")
def home():

    return render_template("index.html")


# --------------------------------
# PDF UPLOAD
# --------------------------------

@app.route("/upload", methods=["GET", "POST"])
def upload():

    global extracted_content
    global generated_questions

    if request.method == "POST":

        if "pdf_file" not in request.files:
            return "Please select a PDF file."

        file = request.files["pdf_file"]

        if file.filename == "":
            return "No file selected."

        if not file.filename.lower().endswith(".pdf"):
            return "Only PDF files are allowed."

        filename = os.path.basename(file.filename)

        filepath = os.path.join(
            UPLOAD_FOLDER, filename
        )

        file.save(filepath)

        extracted_content = []
        generated_questions = []

        try:
            document = fitz.open(filepath)

            for page_number, page in enumerate(
                document, start=1
            ):

                text = page.get_text()

                if text.strip():

                    extracted_content.append({
                        "page": page_number,
                        "content": text
                    })

            document.close()

        except Exception:
            return "Unable to read this PDF. Please try another file."

        session.clear()

        return render_template(
            "upload.html",
            success=True,
            filename=filename,
            pages=len(extracted_content),
            content=extracted_content
        )

    return render_template(
        "upload.html",
        success=False
    )


# --------------------------------
# GENERATE ADAPTIVE QUIZ
# --------------------------------

@app.route("/generate", methods=["POST"])
def generate():

    global generated_questions

    generated_questions = generate_questions(
        extracted_content
    )

    if not generated_questions:

        return """
        <h2>Unable to generate questions</h2>
        <p>Please upload a PDF with more readable text.</p>
        <a href="/upload">Go Back</a>
        """

    # Limit each assessment to 10 questions
    random.shuffle(generated_questions)
    generated_questions = generated_questions[:10]

    session["used_indices"] = []
    session["results"] = []
    session["target_level"] = 2
    session["total_questions"] = len(generated_questions)

    # Start at Medium difficulty
    first_question = select_next_question(2)

    session["current_question"] = first_question
    session["used_indices"] = [first_question]

    return redirect(url_for("quiz"))


# --------------------------------
# DISPLAY ONE QUESTION AT A TIME
# --------------------------------

@app.route("/quiz")
def quiz():

    if "current_question" not in session:
        return redirect(url_for("upload"))

    question_index = session["current_question"]

    question = generated_questions[question_index]

    return render_template(
        "quiz.html",
        current_question=question,
        question_number=len(session["used_indices"]),
        total=session["total_questions"],
        answered=len(session["results"])
    )


# --------------------------------
# CHECK ANSWER AND ADAPT
# --------------------------------

@app.route("/answer", methods=["POST"])
def answer():

    if "current_question" not in session:
        return redirect(url_for("upload"))

    question_index = session["current_question"]

    question = generated_questions[question_index]

    selected_answer = request.form.get("answer")

    if selected_answer not in question["options"]:
        return redirect(url_for("quiz"))

    correct_answer = question["answer"]

    is_correct = selected_answer == correct_answer

    # Save result
    results = session.get("results", [])

    results.append({

        "question": question["question"],
        "selected": selected_answer,
        "correct": correct_answer,
        "is_correct": is_correct,
        "page": question["page"],
        "topic": question["topic"],
        "difficulty": question["difficulty"]

    })

    session["results"] = results

    # Adapt next difficulty
    current_level = session["target_level"]

    if is_correct:
        next_level = min(3, current_level + 1)
    else:
        next_level = max(1, current_level - 1)

    session["target_level"] = next_level

    # Finish when all questions have been answered
    if len(results) >= session["total_questions"]:

        return redirect(url_for("result"))

    # Select next question
    next_question = select_next_question(next_level)

    if next_question is None:
        return redirect(url_for("result"))

    used = session.get("used_indices", [])
    used.append(next_question)

    session["used_indices"] = used
    session["current_question"] = next_question

    return redirect(url_for("quiz"))


# --------------------------------
# RESULTS AND TOPIC ANALYSIS
# --------------------------------

@app.route("/result")
def result():

    results = session.get("results", [])

    total = len(results)

    score = sum(
        1 for item in results
        if item["is_correct"]
    )

    percentage = (
        round(score / total * 100)
        if total else 0
    )

    topic_summary = {}

    for item in results:

        topic = item["topic"]

        if topic not in topic_summary:
            topic_summary[topic] = {
                "correct": 0,
                "total": 0
            }

        topic_summary[topic]["total"] += 1

        if item["is_correct"]:
            topic_summary[topic]["correct"] += 1

    return render_template(
        "result.html",
        score=score,
        total=total,
        percentage=percentage,
        results=results,
        topic_summary=topic_summary
    )


# --------------------------------
# RUN APPLICATION
# --------------------------------

if __name__ == "__main__":

    app.run(debug=True)
