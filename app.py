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
    """Limpa arquivos temporários das pastas"""
    try:
        for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
            for filename in os.listdir(folder):
                if filename == 'images': 
                    continue 
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path): 
                    os.unlink(file_path)
    except Exception as e:
        print(f"Erro ao limpar pastas: {e}")

def gerar_spek(audio_path, title):
    """Gera espectrograma do áudio"""
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
        print(f"Erro ao gerar espectrograma: {e}")
        return None

def editar_metadados(file_path, artist=None, title=None, album=None, cover_url=None):
    """Edita metadados ID3 do arquivo de áudio"""
    try:
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.mp3':
            audio = MP3(file_path, ID3=ID3)
            try:
                audio.delete()
            except:
                pass
            
            audio.add_tags()
            
            if title:
                audio.tags.add(TIT2(encoding=3, text=title))
            if artist:
                audio.tags.add(TPE1(encoding=3, text=artist))
            if album:
                audio.tags.add(TALB(encoding=3, text=album))
            
            if cover_url:
                try:
                    response = requests.get(cover_url, timeout=10)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content))
                        img = img.resize((500, 500), Image.Resampling.LANCZOS)
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        img_bytes.seek(0)
                        
                        audio.tags.add(
                            APIC(
                                encoding=3,
                                mime='image/jpeg',
                                type=3,
                                desc='Cover',
                                data=img_bytes.read()
                            )
                        )
                except Exception as e:
                    print(f"Erro ao adicionar capa: {e}")
            
            audio.save()
        
        elif ext == '.flac':
            audio = FLAC(file_path)
            if title:
                audio['title'] = title
            if artist:
                audio['artist'] = artist
            if album:
                audio['album'] = album
            audio.save()
        
        elif ext == '.wav':
            try:
                audio = WAVE(file_path)
                audio.add_tags()
                if title:
                    audio['TIT2'] = TIT2(encoding=3, text=title)
                if artist:
                    audio['TPE1'] = TPE1(encoding=3, text=artist)
                audio.save()
            except:
                pass
        
        return True
    except Exception as e:
        print(f"Erro ao editar metadados: {e}")
        return False

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static/images'), 
        'favicon.ico'
    )

# ===================================
# AUTENTICAÇÃO
# ===================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash('E-mail não encontrado. Deseja criar uma conta?', 'error')
            return render_template('login.html')
        
        if not check_password_hash(user.password_hash, password):
            flash('Senha incorreta. Tente novamente.', 'error')
            return render_template('login.html')
        
        login_user(user)
        
        if not user.is_subscriber:
            flash('Complete o pagamento para liberar o acesso!', 'error')
            return redirect(url_for('payment'))
        
        flash('Login realizado com sucesso!', 'success')
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
        
        if not email or not dj_name or not password:
            flash('Preencha todos os campos!', 'error')
            return render_template('register.html')
        
        if len(password) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'error')
            return render_template('register.html')
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Este e-mail já está cadastrado. Faça login!', 'error')
            return render_template('register.html')
        
        try:
            new_user = User(email=email, dj_name=dj_name)
            new_user.set_password(password)
            new_user.generate_referral()
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user)
            flash('Conta criada com sucesso! Complete o pagamento.', 'success')
            return redirect(url_for('payment'))
        except Exception as e:
            db.session.rollback()
            flash('Erro ao criar conta. Tente novamente.', 'error')
            print(f"Erro no registro: {e}")
            return render_template('register.html')
            
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))

# ===================================
# PAGAMENTO PIX - MERCADO PAGO
# ===================================

@app.route('/payment')
@login_required
def payment():
    """Tela de pagamento PIX"""
    if current_user.is_subscriber:
        return redirect(url_for('index'))
    
    # Verifica se já existe um pagamento pendente
    pending_payment = Payment.query.filter_by(
        user_id=current_user.id,
        status='pending'
    ).first()
    
    return render_template('payment.html', 
                          user=current_user,
                          pending_payment=pending_payment)

@app.route('/create_pix_payment', methods=['POST'])
@login_required
def create_pix_payment():
    """Cria uma preferência de pagamento PIX no Mercado Pago"""
    
    if not sdk:
        return jsonify({
            'error': 'Mercado Pago não configurado. Configure MERCADOPAGO_ACCESS_TOKEN no .env'
        }), 500
    
    try:
        # Gera referência única
        external_reference = f"VIBE-{current_user.id}-{uuid.uuid4().hex[:8].upper()}"
        
        # Cria preferência de pagamento
        preference_data = {
            "items": [
                {
                    "title": "VibeDownloader - Assinatura Mensal",
                    "quantity": 1,
                    "unit_price": 25.00,
                    "currency_id": "BRL"
                }
            ],
            "payer": {
                "name": current_user.dj_name,
                "email": current_user.email
            },
            "payment_methods": {
                "excluded_payment_types": [
                    {"id": "credit_card"},
                    {"id": "debit_card"},
                    {"id": "ticket"}
                ],
                "installments": 1
            },
            "external_reference": external_reference,
            "notification_url": f"{os.getenv('APP_URL', 'http://localhost:5002')}/webhook/mercadopago",
            "back_urls": {
                "success": f"{os.getenv('APP_URL', 'http://localhost:5002')}/payment/success",
                "failure": f"{os.getenv('APP_URL', 'http://localhost:5002')}/payment/failure",
                "pending": f"{os.getenv('APP_URL', 'http://localhost:5002')}/payment/pending"
            },
            "auto_return": "approved",
            "expires": True,
            "expiration_date_from": datetime.utcnow().isoformat(),
            "expiration_date_to": (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
        
        # Cria preferência no MP
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        
        # Salva no banco
        new_payment = Payment(
            user_id=current_user.id,
            preference_id=preference["id"],
            external_reference=external_reference,
            amount=25.00,
            status='pending',
            payment_method='pix',
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
        # Busca dados do PIX
        if "point_of_interaction" in preference and "transaction_data" in preference["point_of_interaction"]:
            transaction_data = preference["point_of_interaction"]["transaction_data"]
            new_payment.pix_qr_code = transaction_data.get("qr_code_base64")
            new_payment.pix_code = transaction_data.get("qr_code")
        
        db.session.add(new_payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'preference_id': preference["id"],
            'init_point': preference["init_point"],
            'qr_code': new_payment.pix_qr_code,
            'qr_code_text': new_payment.pix_code
        })
        
    except Exception as e:
        print(f"Erro ao criar pagamento: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/webhook/mercadopago', methods=['POST'])
def mercadopago_webhook():
    """Webhook para receber notificações do Mercado Pago"""
    
    if not sdk:
        return jsonify({'error': 'MP not configured'}), 500
    
    try:
        data = request.json
        
        # Verifica se é notificação de pagamento
        if data.get('type') == 'payment':
            payment_id = data['data']['id']
            
            # Busca informações do pagamento no MP
            payment_info = sdk.payment().get(payment_id)
            payment_data = payment_info["response"]
            
            external_reference = payment_data.get('external_reference')
            status = payment_data.get('status')
            
            # Busca pagamento no banco
            payment_record = Payment.query.filter_by(
                external_reference=external_reference
            ).first()
            
            if payment_record:
                payment_record.payment_id = str(payment_id)
                payment_record.status = status
                
                # Se aprovado, ativa assinatura
                if status == 'approved':
                    payment_record.approved_at = datetime.utcnow()
                    
                    user = User.query.get(payment_record.user_id)
                    if user:
                        user.is_subscriber = True
                        user.subscription_expires = datetime.utcnow() + timedelta(days=30)
                
                db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Erro no webhook: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/payment/check/<external_reference>')
@login_required
def check_payment_status(external_reference):
    """Verifica status de um pagamento"""
    payment = Payment.query.filter_by(
        external_reference=external_reference,
        user_id=current_user.id
    ).first()
    
    if not payment:
        return jsonify({'error': 'Pagamento não encontrado'}), 404
    
    return jsonify({
        'status': payment.status,
        'approved': payment.status == 'approved'
    })

@app.route('/payment/success')
@login_required
def payment_success():
    flash('Pagamento aprovado! Bem-vindo ao Vibe Studio!', 'success')
    return redirect(url_for('index'))

@app.route('/payment/failure')
@login_required
def payment_failure():
    flash('Pagamento recusado. Tente novamente.', 'error')
    return redirect(url_for('payment'))

@app.route('/payment/pending')
@login_required
def payment_pending():
    flash('Pagamento pendente. Aguardando confirmação...', 'warning')
    return redirect(url_for('payment'))

# ===================================
# DOWNLOADER
# ===================================

@app.route('/', methods=['GET', 'POST'])
def index():
    if not current_user.is_authenticated:
        return render_template('landing.html')

    if not current_user.is_subscriber:
        return redirect(url_for('payment'))

    if request.method == 'POST':
        limpar_pastas()
        raw_urls = request.form.getlist('urls[]')
        urls = [u.strip() for u in raw_urls if u.strip()]
        format_type = request.form.get('format', 'mp3')

        if not urls: 
            flash('Adicione pelo menos um link válido.', 'error')
            return redirect(url_for('index'))

        files_info = []
        downloaded_paths = []

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'ffmpeg_location': FFMPEG_PATH,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_type,
                'preferredquality': '320',
            }],
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    try:
                        info = ydl.extract_info(url, download=True)
                        filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{format_type}'
                        
                        if os.path.exists(filename):
                            title = info.get('title', 'Audio')
                            artist = info.get('artist') or info.get('uploader', 'Desconhecido')
                            thumbnail = info.get('thumbnail')
                            
                            spec = gerar_spek(filename, title)
                            
                            files_info.append({
                                'title': title,
                                'artist': artist,
                                'thumbnail': thumbnail,
                                'spectrogram': spec,
                                'filename': os.path.basename(filename)
                            })
                            downloaded_paths.append(filename)
                    except Exception as e:
                        print(f"Erro no download individual: {e}")
                        continue
            
            if not downloaded_paths:
                flash('Não foi possível baixar nenhum arquivo. Verifique os links.', 'error')
                return redirect(url_for('index'))

            if len(downloaded_paths) == 1:
                return render_template('index.html',
                                       show_metadata_editor=True,
                                       file_info=files_info[0],
                                       format_type=format_type)
            else:
                data_hora = datetime.now().strftime("%d-%m-%Hh%M")
                zip_name = f"Vibe_Mix_{data_hora}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
                
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    for f in downloaded_paths:
                        zf.write(f, os.path.basename(f))
                
                return render_template('index.html', 
                                       download_ready=True, 
                                       results=files_info, 
                                       final_filename=zip_name,
                                       is_zip=True,
                                       total_files=len(downloaded_paths))

        except Exception as e:
            flash(f'Erro no processamento: {str(e)}', 'error')
            print(f"Erro geral: {e}")
            return redirect(url_for('index'))

    return render_template('index.html', download_ready=False)

@app.route('/apply_metadata', methods=['POST'])
@login_required
def apply_metadata():
    if not current_user.is_subscriber:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        filename = request.form.get('filename')
        artist = request.form.get('artist', '').strip()
        title = request.form.get('title', '').strip()
        album = request.form.get('album', '').strip()
        cover_url = request.form.get('cover_url', '').strip()
        
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Arquivo não encontrado'}), 404
        
        success = editar_metadados(file_path, artist, title, album, cover_url)
        
        if success:
            return jsonify({
                'success': True,
                'download_url': url_for('download_file', filename=filename)
            })
        else:
            return jsonify({'error': 'Erro ao editar metadados'}), 500
            
    except Exception as e:
        print(f"Erro ao aplicar metadados: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    if not current_user.is_subscriber: 
        return redirect(url_for('payment'))
    
    try:
        return send_file(
            os.path.join(DOWNLOAD_FOLDER, filename), 
            as_attachment=True
        )
    except Exception as e:
        flash('Arquivo não encontrado ou expirado.', 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5002)