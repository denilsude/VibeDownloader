from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False) # Mudou para Email
    dj_name = db.Column(db.String(150), nullable=False)            # Novo: Nome Artístico
    password_hash = db.Column(db.String(200), nullable=False)
    
    # Controle Comercial
    credits = db.Column(db.Float, default=0.0)
    is_subscriber = db.Column(db.Boolean, default=False) # TRAVA: Só entra se for True
    referral_code = db.Column(db.String(50), unique=True)
    referred_by = db.Column(db.String(50), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_referral(self):
        if not self.referral_code:
            self.referral_code = str(uuid.uuid4())[:8]