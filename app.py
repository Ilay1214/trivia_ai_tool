from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import os
from werkzeug.utils import secure_filename
from ai_service import read_file_content, generate_quiz_questions
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship

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
            'correct_answer': self.correct_answer
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

        # Parse generated questions and save to database
        new_quiz = Quiz(num_questions=num_questions, time_limit=time_limit)
        db.session.add(new_quiz)
        db.session.commit() # Commit to get quiz.id

        # Split the generated questions into individual question blocks
        question_blocks = generated_questions.strip().split('\n\n')
        for block in question_blocks:
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if not lines: continue

            question_text = ""
            options = []
            correct_answer = ""

            # Parse question text and options
            for line in lines:
                if line.startswith(f'{question_blocks.index(block) + 1}.'):
                    question_text = line.split('. ', 1)[1]
                elif line.startswith(('A)', 'B)', 'C)', 'D)')):
                    options.append(line)
                elif line.startswith('Correct Answer:'):
                    correct_answer = line.split(':', 1)[1].strip()

            if len(options) == 4 and question_text and correct_answer:
                new_question = Question(
                    quiz_id=new_quiz.id,
                    question_text=question_text,
                    option_a=options[0] if len(options) > 0 else '',
                    option_b=options[1] if len(options) > 1 else '',
                    option_c=options[2] if len(options) > 2 else '',
                    option_d=options[3] if len(options) > 3 else '',
                    correct_answer=correct_answer
                )
                db.session.add(new_question)
            else:
                print(f"Skipping malformed question block: {block}")

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

    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({'error': 'Quiz not found'}), 404

    score = 0
    total_questions = len(quiz.questions)

    for question in quiz.questions:
        question_id = str(question.id) # Ensure key matches frontend (string)
        if question_id in user_answers:
            if user_answers[question_id] == question.correct_answer:
                score += 1
    
    return jsonify({'score': score, 'total_questions': total_questions})

if __name__ == '__main__':
    app.run(debug=True)