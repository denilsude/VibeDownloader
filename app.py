import os
import shutil
import zipfile
import time
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa
import librosa.display
import numpy as np
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, send_from_directory, jsonify
from yt_dlp import YoutubeDL
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.wave import WAVE
import requests
from io import BytesIO
from PIL import Image
import mercadopago
from dotenv import load_dotenv
import uuid
import sqlite3

# Carrega variáveis de ambiente
load_dotenv()

# Banco e Login
# [MODIFICAÇÃO 1] Adicionado 'Coupon' na importação
from models import db, User, Payment, Coupon
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'vibe_secret_key_pro_dj_2024_ultra_secure')

# Banco de Dados
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'vibe.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Mercado Pago SDK
MP_ACCESS_TOKEN = os.getenv('MERCADOPAGO_ACCESS_TOKEN')
sdk = mercadopago.SDK(MP_ACCESS_TOKEN) if MP_ACCESS_TOKEN else None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===================================
# SISTEMA DE MIGRAÇÃO AUTOMÁTICA
# ===================================

def verificar_e_migrar_banco():
    """
    Verifica se o banco tem o schema correto e cria tabela Coupon se faltar.
    """
    try:
        if not os.path.exists(DATABASE_PATH):
            print("⚠️ Banco de dados não encontrado. Criando novo...")
            with app.app_context():
                db.create_all()
            print("✅ Banco criado com sucesso!")
            return
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # 1. Verifica tabela User
        cursor.execute("PRAGMA table_info(user)")
        colunas_existentes = [col[1] for col in cursor.fetchall()]
        colunas_necessarias = [
            'id', 'email', 'dj_name', 'password_hash',
            'credits', 'is_subscriber', 'subscription_expires',
            'referral_code', 'referred_by', 'created_at', 'updated_at'
        ]
        
        colunas_faltando = [col for col in colunas_necessarias if col not in colunas_existentes]
        
        if colunas_faltando:
            print(f"🔧 Migrando User: Faltam {colunas_faltando}")
            for coluna in colunas_faltando:
                try:
                    if coluna == 'credits': cursor.execute("ALTER TABLE user ADD COLUMN credits REAL DEFAULT 0.0")
                    elif coluna == 'is_subscriber': cursor.execute("ALTER TABLE user ADD COLUMN is_subscriber BOOLEAN DEFAULT 0")
                    elif coluna == 'subscription_expires': cursor.execute("ALTER TABLE user ADD COLUMN subscription_expires DATETIME")
                    elif coluna == 'referral_code': cursor.execute("ALTER TABLE user ADD COLUMN referral_code VARCHAR(50)")
                    elif coluna == 'referred_by': cursor.execute("ALTER TABLE user ADD COLUMN referred_by VARCHAR(50)")
                    elif coluna == 'created_at': cursor.execute("ALTER TABLE user ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                    elif coluna == 'updated_at': cursor.execute("ALTER TABLE user ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                except Exception as e: print(f"Erro coluna {coluna}: {e}")
            conn.commit()

        # 2. Verifica tabela Payment (cria se não existir)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payment'")
        if not cursor.fetchone():
            print("⚠️ Tabela 'payment' não existe. Criando via SQLAlchemy...")
            with app.app_context():
                db.create_all()

        # 3. Verifica tabela Coupon (NOVO - cria se não existir)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coupon'")
        if not cursor.fetchone():
            print("⚠️ Tabela 'coupon' não existe. Criando via SQLAlchemy...")
            with app.app_context():
                db.create_all()
                
        conn.close()
        
    except Exception as e:
        print(f"❌ ERRO BANCO: {e}")

# Executa migração ao iniciar
with app.app_context():
    verificar_e_migrar_banco()

DOWNLOAD_FOLDER = 'downloads'
STATIC_FOLDER = 'static'

for f in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
    if not os.path.exists(f): 
        os.makedirs(f)

FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

def limpar_pastas():
    try:
        for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
            for filename in os.listdir(folder):
                if filename == 'images': continue 
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path): os.unlink(file_path)
    except Exception as e:
        print(f"Erro ao limpar pastas: {e}")

def gerar_spek(audio_path, title):
    try:
        y, sr = librosa.load(audio_path, duration=60)
        plt.style.use('dark_background')
        plt.figure(figsize=(8, 3))
        D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
        librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='hz', cmap='inferno')
        plt.colorbar(format='%+2.0f dB')
        plt.title(f'{title[:40]}...', fontsize=10, color='white')
        plt.tight_layout()
        img_name = f"spec_{int(time.time())}_{np.random.randint(100)}.png"
        img_path = os.path.join(STATIC_FOLDER, img_name)
        plt.savefig(img_path, facecolor='#1e1e1e', edgecolor='none')
        plt.close()
        return img_name
    except Exception as e:
        print(f"Erro spek: {e}")
        return None

def editar_metadados(file_path, artist=None, title=None, album=None, cover_url=None):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.mp3':
            audio = MP3(file_path, ID3=ID3)
            try: audio.delete()
            except: pass
            audio.add_tags()
            if title: audio.tags.add(TIT2(encoding=3, text=title))
            if artist: audio.tags.add(TPE1(encoding=3, text=artist))
            if album: audio.tags.add(TALB(encoding=3, text=album))
            if cover_url:
                try:
                    resp = requests.get(cover_url, timeout=10)
                    if resp.status_code == 200:
                        img = Image.open(BytesIO(resp.content)).resize((500, 500))
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_bytes.getvalue()))
                except: pass
            audio.save()
        return True
    except Exception as e:
        print(f"Erro metadados: {e}")
        return False

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'), 'favicon.ico')

# ===================================
# AUTENTICAÇÃO E CADASTRO
# ===================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        
        if not user or not check_password_hash(user.password_hash, password):
            flash('Login incorreto.', 'error')
            return render_template('login.html')
        
        login_user(user)
        
        # Se tem cupom ativo ou pagou
        if user.is_subscriber and user.subscription_expires:
            if user.subscription_expires < datetime.utcnow():
                user.is_subscriber = False
                db.session.commit()
                flash('Sua assinatura expirou.', 'error')
                return redirect(url_for('payment'))

        if not user.is_subscriber:
            return redirect(url_for('payment'))
        
        return redirect(url_for('index'))
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        dj_name = request.form.get('dj_name', '').strip()
        password = request.form.get('password', '')
        
        # [MODIFICAÇÃO 2] Captura o código do cupom
        coupon_code = request.form.get('coupon_code', '').strip().upper()
        
        if User.query.filter_by(email=email).first():
            flash('E-mail já cadastrado.', 'error')
            return render_template('register.html')
        
        try:
            new_user = User(email=email, dj_name=dj_name)
            new_user.set_password(password)
            new_user.generate_referral()
            
            # [MODIFICAÇÃO 3] Lógica de Validação do Cupom
            cupom_valido = False
            if coupon_code:
                coupon = Coupon.query.filter_by(code=coupon_code, active=True).first()
                if coupon:
                    new_user.is_subscriber = True
                    # Soma os dias do cupom à data atual
                    new_user.subscription_expires = datetime.utcnow() + timedelta(days=coupon.days)
                    cupom_valido = True
                else:
                    flash('Cupom inválido. Conta criada, mas sem acesso VIP.', 'error')
            
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user)
            
            if cupom_valido:
                flash(f'Bem-vindo! Cupom {coupon_code} aplicado com sucesso.', 'success')
                return redirect(url_for('index'))
            else:
                return redirect(url_for('payment'))

        except Exception as e:
            db.session.rollback()
            flash('Erro no cadastro.', 'error')
            print(f"Erro Register: {e}")
            return render_template('register.html')
            
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ===================================
# [MODIFICAÇÃO 4] ROTA SECRETA PARA CRIAR CUPOM
# ===================================
@app.route('/setup-coupons')
def setup_coupons():
    """Rota utilitária para criar o cupom VIBE30"""
    try:
        # Verifica se já existe para não duplicar
        if not Coupon.query.filter_by(code='VIBE30').first():
            c1 = Coupon(code='VIBE30', days=30, active=True)
            db.session.add(c1)
            db.session.commit()
            return "✅ Cupom VIBE30 (30 dias) criado com sucesso!"
        return "⚠️ Cupom VIBE30 já existe."
    except Exception as e:
        return f"Erro ao criar cupom: {e}"

# ===================================
# PAGAMENTO
# ===================================

@app.route('/payment')
@login_required
def payment():
    if current_user.is_subscriber: return redirect(url_for('index'))
    pending_payment = Payment.query.filter_by(user_id=current_user.id, status='pending').first()
    return render_template('payment.html', user=current_user, pending_payment=pending_payment)

@app.route('/create_pix_payment', methods=['POST'])
@login_required
def create_pix_payment():
    if not sdk: return jsonify({'error': 'Mercado Pago Error'}), 500
    try:
        external_ref = f"VIBE-{current_user.id}-{uuid.uuid4().hex[:8].upper()}"
        payment_data = {
            "transaction_amount": 25.00,
            "description": "VibeDownloader - Mensal",
            "payment_method_id": "pix",
            "payer": {"email": current_user.email, "first_name": current_user.dj_name},
            "external_reference": external_ref,
            "notification_url": f"{os.getenv('APP_URL')}/webhook/mercadopago"
        }
        
        result = sdk.payment().create(payment_data)
        pix_data = result["response"]
        
        qr_code = pix_data['point_of_interaction']['transaction_data']['qr_code_base64']
        qr_code_text = pix_data['point_of_interaction']['transaction_data']['qr_code']
        
        new_payment = Payment(
            user_id=current_user.id, payment_id=str(pix_data['id']),
            external_reference=external_ref, amount=25.00,
            pix_qr_code=qr_code, pix_code=qr_code_text,
            expires_at=datetime.utcnow() + timedelta(days=1)
        )
        db.session.add(new_payment)
        db.session.commit()
        
        return jsonify({'success': True, 'qr_code': qr_code, 'qr_code_text': qr_code_text, 'external_reference': external_ref})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook/mercadopago', methods=['POST'])
def webhook():
    try:
        data = request.json
        if data.get('action') == 'payment.created' or data.get('type') == 'payment':
            pid = data['data']['id']
            pay_info = sdk.payment().get(pid)['response']
            ext_ref = pay_info['external_reference']
            status = pay_info['status']
            
            p = Payment.query.filter_by(external_reference=ext_ref).first()
            if p:
                p.status = status
                if status == 'approved':
                    p.approved_at = datetime.utcnow()
                    u = User.query.get(p.user_id)
                    u.is_subscriber = True
                    u.subscription_expires = datetime.utcnow() + timedelta(days=30)
                db.session.commit()
        return jsonify({'success': True})
    except: return jsonify({'error': 'fail'}), 500

@app.route('/payment/check/<external_reference>')
@login_required
def check_status(external_reference):
    p = Payment.query.filter_by(external_reference=external_reference, user_id=current_user.id).first()
    if p and p.status == 'approved':
        current_user.is_subscriber = True # Força atualização sessão
        return jsonify({'approved': True})
    return jsonify({'approved': False})

# ===================================
# DOWNLOADER E CORE
# ===================================

@app.route('/', methods=['GET', 'POST'])
def index():
    if not current_user.is_authenticated: return render_template('landing.html')
    if not current_user.is_subscriber: return redirect(url_for('payment'))
    
    # Verifica expiração
    if current_user.subscription_expires and current_user.subscription_expires < datetime.utcnow():
        current_user.is_subscriber = False
        db.session.commit()
        return redirect(url_for('payment'))

    if request.method == 'POST':
        limpar_pastas()
        urls = [u.strip() for u in request.form.getlist('urls[]') if u.strip()]
        format_type = request.form.get('format', 'mp3')
        if not urls: return redirect(url_for('index'))

        files_info, downloaded = [], []
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'noplaylist': True, 'quiet': True, 'ffmpeg_location': FFMPEG_PATH,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': format_type, 'preferredquality': '320'}],
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    try:
                        info = ydl.extract_info(url, download=True)
                        fname = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{format_type}'
                        if os.path.exists(fname):
                            spec = gerar_spek(fname, info.get('title', 'Audio'))
                            files_info.append({'title': info.get('title'), 'artist': info.get('artist'), 'thumbnail': info.get('thumbnail'), 'spectrogram': spec, 'filename': os.path.basename(fname)})
                            downloaded.append(fname)
                    except: continue
            
            if len(downloaded) == 1:
                return render_template('index.html', show_metadata_editor=True, file_info=files_info[0], format_type=format_type)
            elif len(downloaded) > 1:
                zip_name = f"Vibe_Pack_{int(time.time())}.zip"
                with zipfile.ZipFile(f"{DOWNLOAD_FOLDER}/{zip_name}", 'w') as zf:
                    for f in downloaded: zf.write(f, os.path.basename(f))
                return render_template('index.html', download_ready=True, results=files_info, final_filename=zip_name, is_zip=True)
        except Exception as e:
            flash(f'Erro: {e}', 'error')

    return render_template('index.html', download_ready=False)

@app.route('/apply_metadata', methods=['POST'])
@login_required
def apply_metadata():
    fname = request.form.get('filename')
    path = os.path.join(DOWNLOAD_FOLDER, fname)
    if os.path.exists(path):
        editar_metadados(path, request.form.get('artist'), request.form.get('title'), request.form.get('album'), request.form.get('cover_url'))
        return jsonify({'success': True, 'download_url': url_for('download_file', filename=fname)})
    return jsonify({'error': 'Arquivo sumiu'}), 404

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)