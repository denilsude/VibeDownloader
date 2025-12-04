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
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, send_from_directory, jsonify, abort
from yt_dlp import YoutubeDL
from mutagen.easyid3 import EasyID3
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

# Carrega variáveis de ambiente
load_dotenv()

# Banco e Login
from models import db, User, Payment
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'vibe_secret_key_pro_dj_2024_ultra_secure')

# Banco de Dados
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///vibe.db')
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

# Cria tabelas ao iniciar
with app.app_context():
    db.create_all()

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
        print(f"Erro spec: {e}")
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
                    res = requests.get(cover_url, timeout=10)
                    if res.status_code == 200:
                        img = Image.open(BytesIO(res.content)).resize((500, 500))
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        audio.tags.add(APIC(3, 'image/jpeg', 3, 'Cover', img_bytes.getvalue()))
                except: pass
            audio.save()
        return True
    except Exception as e:
        print(f"Erro meta: {e}")
        return False

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'), 'favicon.ico')

# ===================================
# ADMIN / CORTESIA
# ===================================
@app.route('/admin/grant_access')
def grant_access():
    """
    Rota secreta para dar dias grátis.
    Uso: /admin/grant_access?key=SUA_SECRET_KEY&email=dj@email.com&days=30
    """
    key = request.args.get('key')
    email = request.args.get('email')
    days = int(request.args.get('days', 30))
    
    # Proteção simples
    if key != app.secret_key:
        return "Acesso negado", 403
        
    if not email:
        return "E-mail necessário", 400
        
    user = User.query.filter_by(email=email).first()
    if not user:
        return "Usuário não encontrado", 404
        
    # Lógica de adição de dias
    now = datetime.utcnow()
    if user.subscription_expires and user.subscription_expires > now:
        # Se já tem dias, soma
        user.subscription_expires += timedelta(days=days)
    else:
        # Se não tem ou venceu, começa de hoje
        user.subscription_expires = now + timedelta(days=days)
        
    user.is_subscriber = True
    db.session.commit()
    
    return f"Sucesso! {days} dias adicionados para {user.dj_name}. Expira em: {user.subscription_expires}"

# ===================================
# ROTAS NORMAIS
# ===================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, request.form.get('password')):
            flash('Login inválido.', 'error')
            return render_template('login.html')
        login_user(user)
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if User.query.filter_by(email=email).first():
            flash('E-mail já existe.', 'error')
            return render_template('register.html')
        try:
            u = User(email=email, dj_name=request.form.get('dj_name', '').strip())
            u.set_password(request.form.get('password'))
            u.generate_referral()
            db.session.add(u)
            db.session.commit()
            login_user(u)
            return redirect(url_for('payment'))
        except:
            flash('Erro ao criar conta.', 'error')
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/payment')
@login_required
def payment():
    if current_user.is_subscriber and current_user.subscription_expires > datetime.utcnow():
        return redirect(url_for('index'))
    return render_template('payment.html', user=current_user)

@app.route('/create_pix_payment', methods=['POST'])
@login_required
def create_pix_payment():
    if not sdk: return jsonify({'error': 'Configurar MP'}), 500
    try:
        data = request.json
        amount = float(data.get('amount', 25.00))
        if amount not in [15.00, 20.00, 25.00]: return jsonify({'error': 'Valor inválido'}), 400
        
        ext_ref = f"VIBE-{current_user.id}-{uuid.uuid4().hex[:8]}"
        pref_data = {
            "items": [{"title": "Vibe Access", "quantity": 1, "unit_price": amount, "currency_id": "BRL"}],
            "payer": {"email": current_user.email},
            "payment_methods": {"excluded_payment_types": [{"id": "credit_card"}], "installments": 1},
            "external_reference": ext_ref,
            "notification_url": f"{os.getenv('APP_URL')}/webhook/mercadopago"
        }
        
        pref = sdk.preference().create(pref_data)["response"]
        pay = Payment(user_id=current_user.id, external_reference=ext_ref, amount=amount, status='pending')
        
        if "point_of_interaction" in pref:
            td = pref["point_of_interaction"]["transaction_data"]
            pay.pix_qr_code = td.get("qr_code_base64")
            pay.pix_code = td.get("qr_code")
            
        db.session.add(pay)
        db.session.commit()
        
        return jsonify({'success': True, 'qr_code': pay.pix_qr_code, 'qr_code_text': pay.pix_code, 'external_reference': ext_ref})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook/mercadopago', methods=['POST'])
def mercadopago_webhook():
    try:
        data = request.json
        if data.get('type') == 'payment':
            pay_info = sdk.payment().get(data['data']['id'])["response"]
            ref = pay_info.get('external_reference')
            status = pay_info.get('status')
            
            pay_rec = Payment.query.filter_by(external_reference=ref).first()
            if pay_rec:
                pay_rec.status = status
                if status == 'approved':
                    pay_rec.approved_at = datetime.utcnow()
                    u = User.query.get(pay_rec.user_id)
                    # Adiciona 30 dias a partir de agora ou do fim da vigência atual
                    now = datetime.utcnow()
                    if u.subscription_expires and u.subscription_expires > now:
                        u.subscription_expires += timedelta(days=30)
                    else:
                        u.subscription_expires = now + timedelta(days=30)
                    u.is_subscriber = True
                db.session.commit()
        return jsonify({'success': True}), 200
    except: return jsonify({'error': 'Webhook falhou'}), 500

@app.route('/payment/check/<ref>')
@login_required
def check_payment(ref):
    p = Payment.query.filter_by(external_reference=ref, user_id=current_user.id).first()
    if p and p.status == 'approved': return jsonify({'approved': True})
    return jsonify({'approved': False})

@app.route('/', methods=['GET', 'POST'])
def index():
    if not current_user.is_authenticated: return render_template('landing.html')
    
    # Verifica expiração
    if not current_user.is_subscriber or (current_user.subscription_expires and current_user.subscription_expires < datetime.utcnow()):
        current_user.is_subscriber = False
        db.session.commit()
        return redirect(url_for('payment'))

    if request.method == 'POST':
        limpar_pastas()
        urls = request.form.getlist('urls[]')
        fmt = request.form.get('format', 'mp3')
        if not urls: return redirect(url_for('index'))
        
        files, paths = [], []
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'noplaylist': True, 'quiet': True, 'ffmpeg_location': FFMPEG_PATH,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': fmt, 'preferredquality': '320'}]
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                for u in urls:
                    if not u.strip(): continue
                    try:
                        info = ydl.extract_info(u, download=True)
                        fname = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{fmt}'
                        if os.path.exists(fname):
                            files.append({
                                'title': info.get('title', 'Audio'),
                                'artist': info.get('artist') or info.get('uploader'),
                                'thumbnail': info.get('thumbnail'),
                                'spectrogram': gerar_spek(fname, info.get('title', 'Audio')),
                                'filename': os.path.basename(fname)
                            })
                            paths.append(fname)
                    except: pass
            
            if len(paths) == 1:
                return render_template('index.html', show_metadata_editor=True, file_info=files[0], format_type=fmt)
            elif len(paths) > 1:
                zip_name = f"Vibe_{int(time.time())}.zip"
                with zipfile.ZipFile(os.path.join(DOWNLOAD_FOLDER, zip_name), 'w') as z:
                    for p in paths: z.write(p, os.path.basename(p))
                return render_template('index.html', download_ready=True, results=files, final_filename=zip_name, is_zip=True)
        except: pass
    
    return render_template('index.html', download_ready=False)

@app.route('/apply_metadata', methods=['POST'])
@login_required
def apply_meta():
    try:
        f = request.form.get('filename')
        p = os.path.join(DOWNLOAD_FOLDER, f)
        if editar_metadados(p, request.form.get('artist'), request.form.get('title'), request.form.get('album'), request.form.get('cover_url')):
            return jsonify({'success': True, 'download_url': url_for('download_file', filename=f)})
        return jsonify({'error': 'Falha na edição'}), 500
    except: return jsonify({'error': 'Erro server'}), 500

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)