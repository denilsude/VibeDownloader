from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    dj_name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    # Controle Comercial
    credits = db.Column(db.Float, default=0.0)
    is_subscriber = db.Column(db.Boolean, default=False)
    subscription_expires = db.Column(db.DateTime, nullable=True)
    
    # Referral System
    referral_code = db.Column(db.String(50), unique=True)
    referred_by = db.Column(db.String(50), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamento com pagamentos
    payments = db.relationship('Payment', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_referral(self):
        if not self.referral_code:
            self.referral_code = str(uuid.uuid4())[:8].upper()

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Mercado Pago Data
    payment_id = db.Column(db.String(100), unique=True, nullable=True)  # ID do MP
    preference_id = db.Column(db.String(100), unique=True, nullable=True)  # ID da preferência
    external_reference = db.Column(db.String(100), unique=True, nullable=False)  # Nosso ID interno
    
    # Payment Info
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='pending')  # pending, approved, rejected, cancelled
    payment_method = db.Column(db.String(50), default='pix')
    
    # PIX Data
    pix_qr_code = db.Column(db.Text, nullable=True)  # QR Code em base64
    pix_code = db.Column(db.Text, nullable=True)  # Código PIX copiável
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<Payment {self.external_reference} - {self.status}>'