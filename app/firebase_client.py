import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore
import os
from dotenv import load_dotenv

load_dotenv()

# Inicializa Firebase Admin una sola vez
if not firebase_admin._apps:
    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    if cred_path:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

db = firestore.client()

def verify_firebase_token(id_token: str) -> dict:
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except Exception as e:
        raise ValueError(f"Token inválido: {e}")
