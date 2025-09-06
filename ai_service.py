import os
from groq import Groq
from docx import Document
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def read_file_content(filepath):
    extension = filepath.rsplit('.', 1)[1].lower()
    content = ""
    if extension == 'txt' or extension == 'md':
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    elif extension == 'docx':
        document = Document(filepath)
        for paragraph in document.paragraphs:
            content += paragraph.text + "\n"
    return content

def generate_quiz_questions(text_content, num_questions):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not found in environment variables.")

    client = Groq(api_key=GROQ_API_KEY)

    # Basic prompt for generating quiz questions
    prompt = f"Given the following text, generate {num_questions} multiple-choice quiz questions. Each question must have exactly 4 options (A, B, C, D) and a single correct answer. Format the output strictly as follows:\n\n1. Question text?\nA) Option A\nB) Option B\nC) Option C\nD) Option D\nCorrect Answer: Option A\n\n2. Second question text?\nA) Option A\nB) Option B\nC) Option C\nD) Option D\nCorrect Answer: Option B\n\n... and so on.\n\nText: {text_content}\n\nQuestions:"

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": f"Given the following text, generate {num_questions} multiple-choice quiz questions. Each question must have exactly 4 options (A, B, C, D) and a single correct answer. Format the output strictly as follows:\n\n1. Question text?\nA) Option A\nB) Option B\nC) Option C\nD) Option D\nCorrect Answer: Option A\n\n2. Second question text?\nA) Option A\nB) Option B\nC) Option C\nD) Option D\nCorrect Answer: Option B\n\n... and so on.\n\nText: {text_content}\n\nQuestions:"
            }
        ],
        model="llama-3.3-70b-versatile", # You can choose other models available on Groq
    )

    return chat_completion.choices[0].message.content
