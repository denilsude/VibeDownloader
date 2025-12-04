import os
import shutil
import zipfile
import time
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa
import librosa.display
import numpy as np
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, send_from_directory
from yt_dlp import YoutubeDL

# Banco e Login
from models import db, User
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'vibe_secret_key_pro_dj_2024_ultra_secure'

# Banco de Dados
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vibe.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Cria tabelas ao iniciar
with app.app_context():
    db.create_all()

DOWNLOAD_FOLDER = 'downloads'
STATIC_FOLDER = 'static'

# Garante pastas
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

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static/images'), 
        'favicon.ico'
    )

# ===================================
# AUTENTICAÇÃO - REFATORADA
# ===================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # Busca usuário
        user = User.query.filter_by(email=email).first()
        
        # FEEDBACK CONTEXTUAL
        if not user:
            flash('E-mail não encontrado. Deseja criar uma conta?', 'error')
            return render_template('login.html')
        
        if not check_password_hash(user.password_hash, password):
            flash('Senha incorreta. Tente novamente.', 'error')
            return render_template('login.html')
        
        # Login bem-sucedido
        login_user(user)
        
        # Redireciona baseado no status de assinatura
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
        
        # Validações
        if not email or not dj_name or not password:
            flash('Preencha todos os campos!', 'error')
            return render_template('register.html')
        
        if len(password) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'error')
            return render_template('register.html')
        
        # Verifica se email já existe
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Este e-mail já está cadastrado. Faça login!', 'error')
            return render_template('register.html')
        
        # Cria novo usuário
        try:
            new_user = User(email=email, dj_name=dj_name)
            new_user.set_password(password)
            new_user.generate_referral()
            db.session.add(new_user)
            db.session.commit()
            
            # Loga automaticamente
            login_user(new_user)
            flash('Conta criada com sucesso! Complete o pagamento.', 'success')
            return redirect(url_for('payment'))
        except Exception as e:
            db.session.rollback()
            flash('Erro ao criar conta. Tente novamente.', 'error')
            print(f"Erro no registro: {e}")
            return render_template('register.html')
            
    return render_template('register.html')

@app.route('/payment')
@login_required
def payment():
    """Tela de pagamento PIX"""
    if current_user.is_subscriber:
        return redirect(url_for('index'))
    return render_template('payment.html', user=current_user)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))

# ===================================
# ÁREA VIP - DOWNLOADER
# ===================================

@app.route('/', methods=['GET', 'POST'])
def index():
    # 1. Se não logado, mostra landing
    if not current_user.is_authenticated:
        return render_template('landing.html')

    # 2. Se não é assinante, redireciona para pagamento
    if not current_user.is_subscriber:
        return redirect(url_for('payment'))

    # 3. Lógica do Downloader
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
                            spec = gerar_spek(filename, title)
                            files_info.append({
                                'title': title, 
                                'spectrogram': spec
                            })
                            downloaded_paths.append(filename)
                    except Exception as e:
                        print(f"Erro no download individual: {e}")
                        continue
            
            if not downloaded_paths:
                flash('Não foi possível baixar nenhum arquivo. Verifique os links.', 'error')
                return redirect(url_for('index'))

            # Gera arquivo final (único ou ZIP)
            final_filename = ""
            is_zip = False

            if len(downloaded_paths) == 1:
                final_filename = os.path.basename(downloaded_paths[0])
                is_zip = False
            else:
                data_hora = datetime.now().strftime("%d-%m-%Hh%M")
                zip_name = f"Vibe_Mix_{data_hora}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
                
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    for f in downloaded_paths:
                        zf.write(f, os.path.basename(f))
                
                final_filename = zip_name
                is_zip = True

            return render_template('index.html', 
                                   download_ready=True, 
                                   results=files_info, 
                                   final_filename=final_filename,
                                   is_zip=is_zip,
                                   total_files=len(downloaded_paths))

        except Exception as e:
            flash(f'Erro no processamento: {str(e)}', 'error')
            print(f"Erro geral: {e}")
            return redirect(url_for('index'))

    return render_template('index.html', download_ready=False)

@app.route('/download/<path:filename>')
@login_required
def download_file(filename):
    """Download do arquivo processado"""
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