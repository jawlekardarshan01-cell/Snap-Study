import re
import smtplib
from email.mime.text import MIMEText

import streamlit as st
from google import genai
from google.genai import types

from prompts import (
    SUMMARY_REQUEST_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)

MODEL_NAME = "gemini-3.5-flash"

st.set_page_config(
    page_title="Snap & Study",
    page_icon="📚",
)

# Load credentials from Streamlit secrets
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
GMAIL_ADDRESS = st.secrets["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"].replace(" ", "")


# -----------------------------
# Client setup
# -----------------------------

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


gemini_client = get_gemini_client()


# -----------------------------
# Email helper functions
# -----------------------------

def is_valid_email(address):
    """Basic email address validation."""
    return bool(
        re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)
    )


def parse_email_summary(text):
    """
    Extract the subject and body from Gemini's response.

    Expected format:
    Subject: Your Study Summary

    Body:
    Hello! Here is your study summary...
    """
    default_subject = "Your Snap & Study Session Summary"
    text = (text or "").strip()

    if not text:
        return default_subject, "No study summary available."

    lines = text.splitlines()

    for index, line in enumerate(lines):
        cleaned_line = line.strip().strip("*")

        if cleaned_line.lower().startswith("subject:"):
            subject = cleaned_line.split(":", 1)[1].strip()
            subject = " ".join(subject.split())[:150]

            body_lines = lines[index + 1:]

            # Remove empty lines after the subject
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)

            # Remove the optional Body: label
            if body_lines:
                first_line = body_lines[0].strip().strip("*").lower()

                if first_line in ("body:", "email body:"):
                    body_lines = body_lines[1:]

            body = "\n".join(body_lines).strip()

            if subject and body:
                return subject, body

    # Fallback if Gemini does not follow the requested format
    return default_subject, text


def send_email(to_address, subject, body):
    """Send an email using Gmail SMTP."""
    try:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = GMAIL_ADDRESS
        message["To"] = to_address

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            timeout=30,
        ) as server:
            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD,
            )
            server.send_message(message)

        return True, "Email sent successfully."

    except Exception as error:
        return False, str(error)


# -----------------------------
# Chat helper functions
# -----------------------------

def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])

        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    message = {
        "role": role,
        "kind": kind,
        "content": content,
    }

    st.session_state.messages.append(message)
    render_message(message)


def ask_gemini(parts):
    try:
        response = st.session_state.chat.send_message(parts)
        return response.text or ""

    except Exception as error:
        return f"Sorry, something went wrong: {error}"


# -----------------------------
# Step 1: Onboarding
# -----------------------------

if "onboarded" not in st.session_state:
    st.title("📚 Snap & Study")
    st.caption("Snap your notes. Understand faster. Study smarter.")

    with st.form("onboarding_form"):
        name = st.text_input("Your name")

        email_address = st.text_input(
            "Your email address",
            placeholder="you@gmail.com",
            help="Your study summary will be sent to this email.",
        )

        submitted = st.form_submit_button("Let's study 🚀")

    if submitted:
        if not name.strip() or not email_address.strip():
            st.warning("Please enter both your name and email address.")

        elif not is_valid_email(email_address.strip()):
            st.warning("Please enter a valid email address.")

        else:
            st.session_state.name = name.strip()
            st.session_state.email_address = email_address.strip()

            st.session_state.chat = gemini_client.chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT
                ),
            )

            st.session_state.messages = []
            st.session_state.onboarded = True

            st.rerun()

    st.stop()


# -----------------------------
# Step 2: Main chat interface
# -----------------------------

header_col, button_col = st.columns(
    [5, 2],
    vertical_alignment="center",
)

with header_col:
    st.title("📚 Snap & Study")


with button_col:
    if st.button(
        "📧 Email Study Summary",
        use_container_width=True,
    ):
        # Require at least one actual user message
        has_study_content = any(
            message["role"] == "user"
            for message in st.session_state.messages
        )

        if not has_study_content:
            st.warning("Ask at least one study question before emailing a summary.")

        else:
            with st.spinner("Preparing your study summary..."):
                summary = ask_gemini([SUMMARY_REQUEST_PROMPT])

            if not summary or summary.startswith(
                "Sorry, something went wrong:"
            ):
                st.error(summary or "Could not generate your study summary.")

            else:
                subject, body = parse_email_summary(summary)

                success, info = send_email(
                    st.session_state.email_address,
                    subject,
                    body,
                )

                if success:
                    st.success(
                        f"Study summary sent to "
                        f"{st.session_state.email_address} 📧"
                    )
                else:
                    st.error(f"Email sending failed: {info}")
st.caption(
    f"Logged in as {st.session_state.name} · "
    f"Study summaries go to {st.session_state.email_address}"
)


# Display the welcome message or previous conversation
if not st.session_state.messages:
    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(
            name=st.session_state.name
        ),
    )

else:
    for message in st.session_state.messages:
        render_message(message)


# -----------------------------
# Step 3: User input
# -----------------------------

user_input = st.chat_input(
    "Ask a question or attach a photo of your notes",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)


if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text

    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()

        add_message(
            "user",
            "image",
            photo_bytes,
        )

        parts.append(
            types.Part.from_bytes(
                data=photo_bytes,
                mime_type=photo.type or "image/jpeg",
            )
        )

    if text:
        add_message("user", "text", text)
        parts.append(text)

    elif photo is not None:
        parts.append(
            "Explain the visible study material in this image. "
            "Identify the topic and provide a clear, "
            "student-friendly explanation."
        )

    if parts:
        with st.spinner("Thinking and preparing your answer..."):
            answer = ask_gemini(parts)

        add_message("assistant", "text", answer)