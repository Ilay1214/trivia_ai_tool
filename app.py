from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from ai_service import read_file_content, generate_quiz_questions
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
import re # Import regex module

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app) # Keep CORS if you anticipate a separate frontend later or for development
app.secret_key = os.getenv("SECRET_KEY")

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define Database Models
class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    num_questions = db.Column(db.Integer, nullable=False)
    time_limit = db.Column(db.Integer, nullable=False)
    questions = relationship('Question', backref='quiz', lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=False)
    option_d = db.Column(db.String(200), nullable=False)
    correct_answer = db.Column(db.String(200), nullable=False) # Stores the full correct option text
    explanation = db.Column(db.Text, nullable=True) # New field for explanation

    def to_dict(self):
        return {
            'id': self.id,
            'question_text': self.question_text,
            'options': [
                self.option_a,
                self.option_b,
                self.option_c,
                self.option_d
            ],
            'correct_answer': self.correct_answer,
            'explanation': self.explanation
        }

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

# Configuration for file uploads
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'md', 'doc', 'docx'} # Note: doc/docx require libraries like python-docx to parse
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_quiz', methods=['POST'])
def generate_quiz():
    if request.method == 'POST':
        # Get number of questions and time limit from form
        num_questions = request.form.get('numQuestions', type=int)
        time_limit = request.form.get('timeLimit', type=int)

        # Handle multiple file uploads
        if 'sourceFile' not in request.files:
            return redirect(url_for('index')) # Redirect back if no file part in request

        files = request.files.getlist('sourceFile') # Get all files with the name 'sourceFile'
        uploaded_filepaths = []
        
        for file in files:
            if file.filename == '':
                continue # Skip empty file fields

            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                uploaded_filepaths.append(filepath)
            else:
                # Handle disallowed file type for any of the files
                # You might want to flash a message to the user
                return f"File type not allowed for {file.filename}!", 400

        if not uploaded_filepaths: # If no valid files were uploaded
            return redirect(url_for('index'))

        # Read content from all uploaded files
        combined_file_content = ""
        for filepath in uploaded_filepaths:
            combined_file_content += read_file_content(filepath) + "\n\n"
        
        # Generate quiz questions using the AI service
        try:
            generated_questions = generate_quiz_questions(combined_file_content, num_questions)
        except ValueError as e:
            # Handle case where API key is missing
            return f"Error: {e}", 500
        except Exception as e:
            # Catch other potential errors from the AI service
            return f"An error occurred during quiz generation: {e}", 500

        print(f"Raw AI Generated Questions: {generated_questions[:1000]}...") # Debug print for raw AI output

        # Parse generated questions and save to database
        new_quiz = Quiz(num_questions=num_questions, time_limit=time_limit)
        db.session.add(new_quiz)
        db.session.commit() # Commit to get quiz.id

        # New parsing logic
        structured_questions = []
        current_question = {}
        question_number_regex = re.compile(r"^\d+\.\s*") # Matches "1. ", "2. ", etc.
        option_regex = re.compile(r"^[A-D]\)\s*") # Matches "A) ", "B) ", etc.

        lines = generated_questions.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line: # Skip empty lines
                continue

            if question_number_regex.match(line):
                # Found a new question
                if current_question:
                    structured_questions.append(current_question)
                current_question = {
                    'question_text': question_number_regex.sub('', line).strip(),
                    'options': [],
                    'correct_answer': '',
                    'explanation': ''
                }
            elif option_regex.match(line) and current_question:
                current_question['options'].append(line)
            elif line.startswith("Correct Answer:") and current_question:
                current_question['correct_answer'] = line.replace("Correct Answer:", "").strip()
            elif line.startswith("Explanation:") and current_question:
                current_question['explanation'] = line.replace("Explanation:", "").strip()

        if current_question: # Add the last question
            structured_questions.append(current_question)

        for q_data in structured_questions:
            if len(q_data['options']) == 4 and q_data['question_text'] and q_data['correct_answer'] and q_data['explanation']:
                new_question = Question(
                    quiz_id=new_quiz.id,
                    question_text=q_data['question_text'],
                    option_a=q_data['options'][0],
                    option_b=q_data['options'][1],
                    option_c=q_data['options'][2],
                    option_d=q_data['options'][3],
                    correct_answer=q_data['correct_answer'],
                    explanation=q_data['explanation']
                )
                db.session.add(new_question)
            else:
                print(f"Skipping malformed structured question: {q_data}") # Debug print for structured data
        
        db.session.commit()

        # Store quiz_id in session instead of raw questions
        session['quiz_id'] = new_quiz.id
        session['num_questions'] = num_questions
        session['time_limit'] = time_limit

        # Redirect to a loading page while AI generates questions
        return redirect(url_for('quiz_loading'))

    return redirect(url_for('index')) # For GET requests to /generate_quiz

@app.route('/api/quiz/<int:quiz_id>')
def get_quiz_data(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    questions_data = [q.to_dict() for q in quiz.questions]
    print(f"API Quiz Data sent to frontend: {questions_data[:500]}...") # Debug print
    return jsonify({
        'id': quiz.id,
        'num_questions': quiz.num_questions,
        'time_limit': quiz.time_limit,
        'questions': questions_data
    })

@app.route('/quiz_loading')
def quiz_loading():
    # This page will display a loading animation and trigger the AI question generation
    # For now, it just shows what's in the session.
    # Retrieve quiz parameters and generated questions from session
    quiz_id = session.get('quiz_id')
    num_questions = session.get('num_questions')
    time_limit = session.get('time_limit')

    if not quiz_id or not num_questions or not time_limit:
        return redirect(url_for('index')) # Go back if session data is missing

    # For now, we will redirect directly to the quiz page since questions are already generated
    return redirect(url_for('quiz'))
@app.route('/quiz')
def quiz():
    quiz_id = session.get('quiz_id')
    num_questions = session.get('num_questions')
    time_limit = session.get('time_limit')

    if not quiz_id or not num_questions or not time_limit:
        return redirect(url_for('index'))

    # Pass quiz_id to the template, which will then fetch the questions via API
    return render_template('quiz.html', 
                           quiz_id=quiz_id,
                           num_questions=num_questions,
                           time_limit=time_limit)

@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    data = request.get_json()
    quiz_id = data.get('quiz_id')
    user_answers = data.get('user_answers', {})

    # Store user answers in session for review on results page
    session[f'quiz_{quiz_id}_user_answers'] = user_answers

    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    score = 0
    total_questions = len(quiz.questions)

    if total_questions == 0:
        return jsonify({'score': 0, 'total_questions': 0, 'percentage_score': 0}), 200

    score_per_question = 100 / total_questions
    percentage_score = 0
    results_breakdown = []

    for question in quiz.questions:
        question_id = str(question.id) # Ensure key matches frontend (string)
        user_answer = user_answers.get(question_id)
        is_correct = (user_answer == question.correct_answer)
        
        if is_correct:
            score += 1
            percentage_score += score_per_question

        results_breakdown.append({
            'question_id': question.id,
            'question_text': question.question_text,
            'user_answer': user_answer,
            'correct_answer': question.correct_answer,
            'is_correct': is_correct,
            'options': [question.option_a, question.option_b, question.option_c, question.option_d]
        })
    
    # Round the percentage score to two decimal places
    percentage_score = round(percentage_score, 2)

    return jsonify({
        'quiz_id': quiz_id,
        'score': score,
        'total_questions': total_questions,
        'percentage_score': percentage_score,
        'results_breakdown': results_breakdown
    })

@app.route('/api/quiz-results/<int:quiz_id>')
def get_quiz_results(quiz_id):
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    # Re-calculate score and breakdown for consistent data return
    score = 0
    total_questions = len(quiz.questions)
    percentage_score = 0
    results_breakdown = []

    if total_questions > 0:
        score_per_question = 100 / total_questions
    
    # For results page, we need to retrieve user answers somehow.
    # For now, we'll assume a dummy user_answers or retrieve from a session if needed for review.
    # In a real app, user answers for a completed quiz would likely be stored in the DB.
    # For this implementation, we will fetch user answers from the session if they exist
    # This is a simplification; a persistent solution would store user answers in the DB.
    user_answers_from_session = session.get(f'quiz_{quiz_id}_user_answers', {})

    for question in quiz.questions:
        user_answer = user_answers_from_session.get(str(question.id))
        is_correct = (user_answer == question.correct_answer)

        if is_correct:
            score += 1
            if total_questions > 0:
                percentage_score += score_per_question
        
        results_breakdown.append({
            'question_id': question.id,
            'question_text': question.question_text,
            'user_answer': user_answer,
            'correct_answer': question.correct_answer,
            'is_correct': is_correct,
            'options': [question.option_a, question.option_b, question.option_c, question.option_d],
            'explanation': question.explanation
        })
    
    percentage_score = round(percentage_score, 2)

    return jsonify({
        'quiz_id': quiz.id,
        'score': score,
        'total_questions': total_questions,
        'percentage_score': percentage_score,
        'results_breakdown': results_breakdown
    })

@app.route('/results/<int:quiz_id>')
def results(quiz_id):
    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return redirect(url_for('index'))
    return render_template('results.html', quiz_id=quiz_id, num_questions=quiz.num_questions)

if __name__ == '__main__':
    app.run(debug=True)