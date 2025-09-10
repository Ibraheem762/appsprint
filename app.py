import streamlit as st
import openai
import sqlite3
import os
from datetime import datetime
import tempfile
import hashlib
import stripe

# Page config
st.set_page_config(
    page_title="Language Learning Podcast Generator",
    page_icon="🎧",
    layout="centered"
)

# Initialize APIs
openai.api_key = st.secrets.get("OPENAI_API_KEY", "your-api-key-here")
stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY", "sk_test_your-stripe-secret-key-here")

# Database setup
def init_db():
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    
    # Create users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, 
                  password_hash TEXT, email TEXT, is_paid BOOLEAN DEFAULT 0)''')
    
    # Check if users table has is_paid column
    c.execute("PRAGMA table_info(users)")
    user_columns = [column[1] for column in c.fetchall()]
    
    if 'is_paid' not in user_columns:
        # Add is_paid column to existing users table
        c.execute("ALTER TABLE users ADD COLUMN is_paid BOOLEAN DEFAULT 0")
    
    # Check if podcasts table exists and has user_id column
    c.execute("PRAGMA table_info(podcasts)")
    podcast_columns = [column[1] for column in c.fetchall()]
    
    if 'user_id' not in podcast_columns:
        # Drop old table and recreate with new schema
        c.execute("DROP TABLE IF EXISTS podcasts")
    
    c.execute('''CREATE TABLE IF NOT EXISTS podcasts
                 (id INTEGER PRIMARY KEY, user_id INTEGER, topic TEXT, difficulty TEXT, 
                  length INTEGER, audio_path TEXT, created_at TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    conn.commit()
    conn.close()

# Auth functions
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def register_user(username, password, email):
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users VALUES (NULL, ?, ?, ?)",
                  (username, hash_password(password), email))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def verify_user(username, password):
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    c.execute("SELECT id, password_hash, is_paid FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    if user and user[1] == hash_password(password):
        return {"id": user[0], "is_paid": bool(user[2])}
    return None

def update_user_payment_status(user_id, is_paid=True):
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_paid=? WHERE id=?", (is_paid, user_id))
    conn.commit()
    conn.close()

def create_stripe_checkout_session():
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Podcast Generator Premium',
                        'description': 'Unlimited podcast generation'
                    },
                    'unit_amount': 999,  # $9.99
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://localhost:8501?payment=success',
            cancel_url='http://localhost:8501?payment=cancel',
        )
        return session.url
    except Exception as e:
        st.error(f"Error creating payment session: {e}")
        return None

def login_page():
    st.title("🎧 Language Learning Podcast Generator")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_btn = st.form_submit_button("Login")
            
            if login_btn:
                user_data = verify_user(username, password)
                if user_data:
                    st.session_state['authenticated'] = True
                    st.session_state['user_id'] = user_data['id']
                    st.session_state['username'] = username
                    st.session_state['is_paid'] = user_data['is_paid']
                    st.rerun()
                else:
                    st.error("Invalid username or password")
    
    with tab2:
        with st.form("register_form"):
            new_username = st.text_input("New Username")
            new_email = st.text_input("Email")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            register_btn = st.form_submit_button("Register")
            
            if register_btn:
                if new_password != confirm_password:
                    st.error("Passwords don't match")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters")
                elif register_user(new_username, new_password, new_email):
                    st.success("Registration successful! Please login.")
                else:
                    st.error("Username already exists")
    
    st.markdown("---")
    st.markdown("**Or continue without account (limited features)**")
    if st.button("Continue as Guest"):
        st.session_state['authenticated'] = False
        st.session_state['user_id'] = None
        st.rerun()

# Generate script
def generate_script(topic, difficulty, length):
    prompt = f"""Create a {difficulty.lower()} level educational script about "{topic}" 
    for language learners. Make it exactly {length} minutes when spoken aloud.
    Use simple vocabulary for easy, intermediate for medium, advanced for hard.
    Make it engaging and conversational."""
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500 * length
        )
        return response.choices[0].message.content
    except:
        return f"Sample script about {topic} at {difficulty} level..."

# Generate audio
def generate_audio(text):
    try:
        response = openai.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text
        )
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
            response.stream_to_file(tmp_file.name)
            return tmp_file.name
    except:
        return None

# Save to database
def save_podcast(topic, difficulty, length, audio_path, user_id=None):
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    c.execute("INSERT INTO podcasts VALUES (NULL, ?, ?, ?, ?, ?, ?)",
              (user_id, topic, difficulty, length, audio_path, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_podcasts(user_id):
    conn = sqlite3.connect('podcasts.db')
    c = conn.cursor()
    if user_id:
        c.execute("SELECT * FROM podcasts WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
    else:
        c.execute("SELECT * FROM podcasts WHERE user_id IS NULL ORDER BY created_at DESC LIMIT 5")
    podcasts = c.fetchall()
    conn.close()
    return podcasts

# Main app
def main():
    init_db()
    
    # Check URL params for payment success
    query_params = st.query_params
    if query_params.get("payment") == "success" and st.session_state.get('user_id'):
        update_user_payment_status(st.session_state['user_id'])
        st.session_state['is_paid'] = True
        st.success("🎉 Payment successful! You now have unlimited access!")
        st.balloons()
    
    # Check if user is logged in
    if 'authenticated' not in st.session_state:
        login_page()
        return
    
    # Header with logout
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("🎧 Language Learning Podcast Generator")
        if st.session_state.get('authenticated'):
            is_paid = st.session_state.get('is_paid', False)
            if is_paid:
                st.markdown(f"Welcome back, **{st.session_state['username']}** 💎")
            else:
                st.markdown(f"Welcome back, **{st.session_state['username']}** (Free)")
        else:
            st.markdown("**Guest Mode** - Limited features")
    
    with col2:
        if st.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    # Payment gate for authenticated users
    if st.session_state.get('authenticated') and not st.session_state.get('is_paid', False):
        st.warning("⚡ **Upgrade to Premium** for unlimited podcast generation!")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Free Plan:**")
            st.markdown("• 3 podcasts per day")
            st.markdown("• Basic topics only")
        with col2:
            st.markdown("**Premium Plan - $9.99:**")
            st.markdown("• ✅ Unlimited podcasts")
            st.markdown("• ✅ All topics & difficulties")
            st.markdown("• ✅ Priority generation")
        
        if st.button("🚀 Upgrade to Premium", type="primary"):
            checkout_url = create_stripe_checkout_session()
            if checkout_url:
                st.markdown(f"[Click here to complete payment]({checkout_url})")
        
        st.markdown("---")
        st.markdown("**Or continue with free plan (limited features below)**")
    
    st.markdown("Generate custom podcasts for passive language learning")
    
    # Input form
    with st.form("podcast_form"):
        topic = st.text_input("Topic", placeholder="e.g., French cuisine, Spanish history...")
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
        length = st.slider("Length (minutes)", 1, 5, 3)
        
        submitted = st.form_submit_button("Generate Podcast")
    
    if submitted and topic:
        with st.spinner("Generating your podcast..."):
            # Generate script
            script = generate_script(topic, difficulty, length)
            st.text_area("Script Preview", script, height=150)
            
            # Generate audio
            audio_path = generate_audio(script)
            
            if audio_path:
                # Play audio
                st.audio(audio_path)
                
                # Download button
                with open(audio_path, "rb") as f:
                    st.download_button(
                        "Download MP3",
                        f.read(),
                        f"{topic}_{difficulty}_{length}min.mp3",
                        "audio/mp3"
                    )
                
                # Save to database
                user_id = st.session_state.get('user_id')
                save_podcast(topic, difficulty, length, audio_path, user_id)
                st.success("Podcast generated successfully!")
            else:
                st.error("Audio generation failed. Please try again.")
    
    # Recent podcasts
    st.markdown("---")
    user_id = st.session_state.get('user_id')
    if user_id:
        st.subheader("Your Podcast History")
    else:
        st.subheader("Recent Guest Podcasts")
    
    podcasts = get_user_podcasts(user_id)
    
    for podcast in podcasts:
        # Adjust index based on whether user_id column exists
        if user_id:
            topic_idx, diff_idx, len_idx, audio_idx, date_idx = 2, 3, 4, 5, 6
        else:
            topic_idx, diff_idx, len_idx, audio_idx, date_idx = 2, 3, 4, 5, 6
            
        with st.expander(f"{podcast[topic_idx]} ({podcast[diff_idx]}) - {podcast[len_idx]} min"):
            if os.path.exists(podcast[audio_idx]):
                st.audio(podcast[audio_idx])
            st.caption(f"Created: {podcast[date_idx]}")

if __name__ == "__main__":
    main()
