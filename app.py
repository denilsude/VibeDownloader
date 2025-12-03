import os
import shutil
import zipfile
import time
import shutil # Para encontrar o executável ffmpeg
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa
import librosa.display
import numpy as np
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, send_from_directory
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.secret_key = 'vibe_secret_key_fixed'

DOWNLOAD_FOLDER = 'downloads'
STATIC_FOLDER = 'static'

# Garante pastas
for f in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
    if not os.path.exists(f): os.makedirs(f)

# DETECTA ONDE ESTÁ O FFMPEG NO SERVIDOR
FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

def limpar_pastas():
    try:
        for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
            for filename in os.listdir(folder):
                # Não deleta a pasta images!
                if filename == 'images': continue 
                
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path): os.unlink(file_path)
    except: pass

def gerar_spek(audio_path, title):
    try:
        y, sr = librosa.load(audio_path, duration=60)
        plt.style.use('dark_background')
        plt.figure(figsize=(8, 3))
        D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
        librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='hz', cmap='inferno')
        plt.colorbar(format='%+2.0f dB')
        plt.title(f'{title[:30]}...', fontsize=10, color='white')
        plt.tight_layout()
        
        img_name = f"spec_{int(time.time())}_{np.random.randint(100)}.png"
        img_path = os.path.join(STATIC_FOLDER, img_name)
        plt.savefig(img_path, facecolor='#1e1e1e', edgecolor='none')
        plt.close()
        return img_name
    except Exception as e:
        print(f"Erro ao gerar Spek para {title}: {e}")
        return None

# Rota especial para servir favicons na raiz
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        limpar_pastas()
        urls = request.form.getlist('urls[]')
        urls = [u for u in urls if u.strip()]
        format_type = request.form.get('format', 'mp3')

        if not urls: return redirect(url_for('index'))

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
                            
                            files_info.append({'title': title, 'spectrogram': spec})
                            downloaded_paths.append(filename)
                    except Exception as e:
                        print(f"Erro no download individual: {e}")
                        continue
            
            if not downloaded_paths:
                flash(f'Erro: Não foi possível baixar. Verifique se o FFmpeg está instalado.', 'error')
                return redirect(url_for('index'))

            zip_name = f"VibePack_{int(time.time())}.zip"
            zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in downloaded_paths:
                    zf.write(f, os.path.basename(f))

            return render_template('index.html', download_ready=True, 
                                   results=files_info, zip_name=zip_name, 
                                   total_files=len(downloaded_paths))

        except Exception as e:
            flash(f'Erro Crítico: {str(e)}', 'error')
            return redirect(url_for('index'))

    return render_template('index.html', download_ready=False)

@app.route('/download/<path:filename>')
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)