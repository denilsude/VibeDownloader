from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    # Parte Comercial
    credits = db.Column(db.Float, default=0.0) # Saldo em Reais (R$)
    is_subscriber = db.Column(db.Boolean, default=False) # Se pagou a mensalidade
    referral_code = db.Column(db.String(50), unique=True) # Código para convidar amigos
    referred_by = db.Column(db.String(50), nullable=True) # Quem indicou esse usuário

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_referral(self):
        if not self.referral_code:
            self.referral_code = str(uuid.uuid4())[:8] # Gera código único curto