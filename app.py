import streamlit as st
import openai
import sqlite3
import hashlib
import os
from datetime import datetime
import tempfile
import requests

st.set_page_config(
    page_title="Language Learning Podcast Generator",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for playful, cozy design
st.markdown("""
<style>
.main {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.stApp > header {
    background: transparent;
}
.css-1d391kg {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.block-container {
    padding-top: 2rem;
    background: rgba(255, 255, 255, 0.95);
    border-radius: 15px;
    margin: 1rem;
}
h1 {
    text-align: center;
    color: #4a4a4a;
    font-family: 'Arial', sans-serif;
    margin-bottom: 2rem;
}
.stSelectbox, .stSlider, .stTextArea {
    margin-bottom: 1rem;
}
.success-message {
    padding: 1rem;
    background: linear-gradient(135deg, #a8e6cf 0%, #88d8a3 100%);
    border-radius: 10px;
    text-align: center;
    margin: 1rem 0;
}
</style>
""", unsafe_allow_html=True)

# Database initialization
def init_database():
    conn = sqlite3.connect('podcast_app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS podcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            length INTEGER NOT NULL,
            format TEXT NOT NULL,
            voice TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Authentication functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    conn = sqlite3.connect('podcast_app.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ? AND password_hash = ?', 
                   (username, hash_password(password)))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def create_user(username, password):
    try:
        conn = sqlite3.connect('podcast_app.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                       (username, hash_password(password)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

# Podcast generation functions
def generate_script(topic, difficulty, length, format_type, language="English"):
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    
    difficulty_prompts = {
        "Easy": "Use simple vocabulary and short sentences. Explain basic concepts clearly.",
        "Medium": "Use intermediate vocabulary with some complex sentences. Include detailed explanations.",
        "Hard": "Use advanced vocabulary and complex sentence structures. Include nuanced discussions."
    }
    
    format_prompts = {
        "Conversation": "Create a natural conversation between two people discussing the topic.",
        "Single narrator": "Create a monologue presentation by a single speaker."
    }
    
    prompt = f"""Create a {difficulty.lower()} level educational script about "{topic}" 
    for language learners. Make it exactly {length} minutes when spoken aloud.
    Use simple vocabulary for easy, intermediate for medium, advanced for hard.
    Make it engaging and conversational.
    
    Format: {format_prompts[format_type]}
    {"If conversation format, clearly mark speakers as 'Speaker 1:' and 'Speaker 2:'" if format_type == "Conversation" else ""}
    
    IMPORTANT: Write enough content to fill exactly {length} minutes of spoken audio.
    This means approximately {length * 180} words of actual spoken content."""
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500 * length
    )
    
    return response.choices[0].message.content

def text_to_speech(text, voice="alloy"):
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        
        response.stream_to_file(tmp_file.name)
        return tmp_file.name

def process_conversation_audio(script, voice1="alloy", voice2="echo"):
    lines = script.split('\n')
    audio_files = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('Speaker 1:'):
            text = line.replace('Speaker 1:', '').strip()
            if text:
                audio_file = text_to_speech(text, voice1)
                audio_files.append(audio_file)
        elif line.startswith('Speaker 2:'):
            text = line.replace('Speaker 2:', '').strip()
            if text:
                audio_file = text_to_speech(text, voice2)
                audio_files.append(audio_file)
        else:
            if not any(line.startswith(speaker) for speaker in ['Speaker 1:', 'Speaker 2:']):
                audio_file = text_to_speech(line, voice1)
                audio_files.append(audio_file)
    
    return audio_files

def save_podcast_history(user_id, topic, difficulty, length, format_type, voice):
    if user_id:
        conn = sqlite3.connect('podcast_app.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO podcasts (user_id, topic, difficulty, length, format, voice)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, topic, difficulty, length, format_type, voice))
        conn.commit()
        conn.close()

def get_user_history(user_id):
    conn = sqlite3.connect('podcast_app.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT topic, difficulty, length, format, voice, created_at
        FROM podcasts WHERE user_id = ?
        ORDER BY created_at DESC LIMIT 10
    ''', (user_id,))
    results = cursor.fetchall()
    conn.close()
    return results

# Initialize database
init_database()

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'username' not in st.session_state:
    st.session_state.username = None

# Main app
st.title("🎧 Language Learning Podcast Generator")
st.markdown("Generate custom podcasts for passive language learning!")

# Sidebar for authentication
with st.sidebar:
    st.header("Account (Optional)")
    
    if not st.session_state.authenticated:
        auth_tab = st.selectbox("Choose action:", ["Login", "Register", "Skip (Anonymous)"])
        
        if auth_tab == "Login":
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                login_submitted = st.form_submit_button("Login")
                
                if login_submitted:
                    user_id = authenticate_user(username, password)
                    if user_id:
                        st.session_state.authenticated = True
                        st.session_state.user_id = user_id
                        st.session_state.username = username
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials")
        
        elif auth_tab == "Register":
            with st.form("register_form"):
                new_username = st.text_input("Username")
                new_password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                register_submitted = st.form_submit_button("Register")
                
                if register_submitted:
                    if new_password != confirm_password:
                        st.error("Passwords don't match")
                    elif len(new_password) < 4:
                        st.error("Password must be at least 4 characters")
                    elif create_user(new_username, new_password):
                        st.success("Account created! Please login.")
                    else:
                        st.error("Username already exists")
    
    else:
        st.success(f"Welcome, {st.session_state.username}!")
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.rerun()
        
        # Show user history
        if st.session_state.user_id:
            st.subheader("Recent Podcasts")
            history = get_user_history(st.session_state.user_id)
            for i, (topic, difficulty, length, format_type, voice, created_at) in enumerate(history):
                with st.expander(f"{topic[:20]}... ({difficulty})"):
                    st.write(f"**Topic:** {topic}")
                    st.write(f"**Difficulty:** {difficulty}")
                    st.write(f"**Length:** {length} min")
                    st.write(f"**Format:** {format_type}")
                    st.write(f"**Created:** {created_at}")

# Main content
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🎯 Podcast Settings")
    
    with st.form("podcast_form"):
        topic = st.text_area("What topic would you like to learn about?", 
                            placeholder="e.g., French cuisine, sustainable energy, space exploration...",
                            height=100)
        
        difficulty = st.selectbox("Difficulty Level", ["Easy", "Medium", "Hard"])
        
        length = st.slider("Podcast Length (minutes)", min_value=1, max_value=10, value=3)
        
        format_type = st.selectbox("Format", ["Conversation", "Single narrator"])
        
        voice = st.selectbox("Voice Style", ["alloy", "echo", "fable", "onyx", "nova", "shimmer"])
        
        language = st.selectbox("Language", ["English", "French"])
        
        generate_submitted = st.form_submit_button("🎵 Generate Podcast", type="primary")

with col2:
    st.subheader("ℹ️ How it works")
    st.markdown("""
    1. **Choose your topic** - anything you're curious about!
    2. **Select difficulty** - from beginner to advanced
    3. **Pick length** - 1-5 minutes perfect for commutes
    4. **Choose format** - conversation or single speaker
    5. **Generate & listen** - play in browser or download
    """)
    
    st.info("💡 **Tip:** Use during commutes, workouts, or relaxing time for passive learning!")

# Podcast generation
if generate_submitted:
    if not topic.strip():
        st.error("Please enter a topic!")
    else:
        with st.spinner("🎨 Generating your personalized podcast..."):
            try:
                # Generate script
                progress_bar = st.progress(0)
                progress_bar.progress(25)
                
                script = generate_script(topic, difficulty, length, format_type, language)
                progress_bar.progress(50)
                
                # Generate audio
                if format_type == "Conversation":
                    audio_files = process_conversation_audio(script)
                    # For simplicity, just use the first audio file
                    audio_file = audio_files[0] if audio_files else None
                else:
                    audio_file = text_to_speech(script, voice)
                
                progress_bar.progress(100)
                
                if audio_file:
                    # Save to history
                    save_podcast_history(st.session_state.user_id, topic, difficulty, length, format_type, voice)
                    
                    # Display results
                    st.markdown('<div class="success-message"><h3>🎉 Your podcast is ready!</h3></div>', 
                               unsafe_allow_html=True)
                    
                    # Audio player
                    with open(audio_file, 'rb') as audio:
                        audio_bytes = audio.read()
                        st.audio(audio_bytes, format='audio/mp3')
                    
                    # Download button
                    st.download_button(
                        label="📥 Download MP3",
                        data=audio_bytes,
                        file_name=f"podcast_{topic[:20].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.mp3",
                        mime="audio/mp3"
                    )
                    
                    # Show script with debugging info
                    script_word_count = len(script.split())
                    with st.expander("📝 View Script"):
                        st.info(f"Script length: {script_word_count} words (target: ~{length * 200} words)")
                        st.text_area("Generated Script:", script, height=300, disabled=True)
                    
                    # Clean up temp file
                    os.unlink(audio_file)
                
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                st.info("Please check your OpenAI API key in Streamlit secrets.")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666;'>"
    "Made with ❤️ for language learners | Powered by OpenAI"
    "</div>", 
    unsafe_allow_html=True
)
