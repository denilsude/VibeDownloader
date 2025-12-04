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

def editar_metadados(file_path, artist=None, title=None, album=None, cover_url=None):
    """Edita metadados ID3 do arquivo de áudio"""
    try:
        ext = os.path.splitext(file_path)[1].lower()
        
        # MP3
        if ext == '.mp3':
            audio = MP3(file_path, ID3=ID3)
            
            # Remove tags antigas
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
            
            # Adiciona capa
            if cover_url:
                try:
                    response = requests.get(cover_url, timeout=10)
                    if response.status_code == 200:
                        # Redimensiona imagem para 500x500 (otimização)
                        img = Image.open(BytesIO(response.content))
                        img = img.resize((500, 500), Image.Resampling.LANCZOS)
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        img_bytes.seek(0)
                        
                        audio.tags.add(
                            APIC(
                                encoding=3,
                                mime='image/jpeg',
                                type=3,  # Cover (front)
                                desc='Cover',
                                data=img_bytes.read()
                            )
                        )
                except Exception as e:
                    print(f"Erro ao adicionar capa: {e}")
            
            audio.save()
        
        # FLAC
        elif ext == '.flac':
            audio = FLAC(file_path)
            if title:
                audio['title'] = title
            if artist:
                audio['artist'] = artist
            if album:
                audio['album'] = album
            
            # Adiciona capa FLAC
            if cover_url:
                try:
                    response = requests.get(cover_url, timeout=10)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content))
                        img = img.resize((500, 500), Image.Resampling.LANCZOS)
                        img_bytes = BytesIO()
                        img.save(img_bytes, format='JPEG')
                        
                        picture = mutagen.flac.Picture()
                        picture.type = 3  # Cover (front)
                        picture.mime = 'image/jpeg'
                        picture.data = img_bytes.getvalue()
                        audio.add_picture(picture)
                except Exception as e:
                    print(f"Erro ao adicionar capa FLAC: {e}")
            
            audio.save()
        
        # WAV (limitado - usa ID3v2)
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
                pass  # WAV tem suporte limitado a tags
        
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

@app.route('/payment')
@login_required
def payment():
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
# DOWNLOADER + EDITOR DE METADADOS
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

            # Se apenas 1 arquivo, vai para edição de metadados
            if len(downloaded_paths) == 1:
                return render_template('index.html',
                                       show_metadata_editor=True,
                                       file_info=files_info[0],
                                       format_type=format_type)
            
            # Se múltiplos, cria ZIP direto
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
    """Aplica metadados editados e finaliza download"""
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
        
        # Aplica metadados
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