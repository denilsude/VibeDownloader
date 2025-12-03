import os
import zipfile
import shutil
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa
import librosa.display
import numpy as np
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.secret_key = 'vibe_key_secret_123'

DOWNLOAD_FOLDER = 'downloads'
STATIC_FOLDER = 'static'

# Limpeza inicial e criação de pastas
for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def limpar_pasta(pasta):
    # Remove arquivos antigos para não lotar o servidor
    for filename in os.listdir(pasta):
        file_path = os.path.join(pasta, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f'Falha ao deletar {file_path}. Razão: {e}')

def gerar_espectrograma(audio_path, title):
    try:
        y, sr = librosa.load(audio_path, duration=60) # Analisa apenas 60s para ser rápido
        plt.figure(figsize=(10, 3))
        D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
        librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='log', cmap='inferno')
        plt.colorbar(format='%+2.0f dB')
        plt.title(f'Vibe Check: {title}')
        plt.tight_layout()
        
        image_filename = f"spec_{int(time.time())}.png"
        image_path = os.path.join(STATIC_FOLDER, image_filename)
        plt.savefig(image_path)
        plt.close()
        return image_filename
    except Exception as e:
        print(f"Erro ao gerar espectro: {e}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Limpar downloads antigos antes de começar
        limpar_pasta(DOWNLOAD_FOLDER)
        limpar_pasta(STATIC_FOLDER)

        raw_urls = request.form.get('urls')
        format_type = request.form.get('format')
        
        if not raw_urls:
            return redirect(url_for('index'))

        # Processar lista de links (separar por quebra de linha ou vírgula)
        urls = [u.strip() for u in raw_urls.replace(',', '\n').split('\n') if u.strip()]
        
        if len(urls) > 10:
            flash('Limite máximo de 10 músicas por vez para garantir qualidade.', 'error')
            return redirect(url_for('index'))

        downloaded_files = []
        last_title = ""

        try:
            # Configuração do FFmpeg para alta qualidade
            ydl_opts = {
                'format': 'bestaudio/best', # Baixa a melhor fonte possível
                'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format_type,
                    'preferredquality': '320' if format_type == 'mp3' else None,
                }],
            }

            with YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{format_type}'
                    downloaded_files.append(filename)
                    last_title = info.get('title', 'Musica')

            # Lógica de Entrega (1 arquivo ou ZIP)
            final_file = ""
            spectrogram_img = None

            if len(downloaded_files) == 1:
                final_file = os.path.basename(downloaded_files[0])
                # Gera espectro apenas se for 1 música (para performance)
                spectrogram_img = gerar_espectrograma(downloaded_files[0], last_title)
            else:
                # Criar ZIP se forem várias
                zip_name = f"VibePack_{int(time.time())}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for file in downloaded_files:
                        zipf.write(file, os.path.basename(file))
                final_file = zip_name

            return render_template('index.html', 
                                   download_ready=True, 
                                   file_name=final_file, 
                                   spectrogram=spectrogram_img)

        except Exception as e:
            flash(f'Erro no processamento: {str(e)}', 'error')
            return redirect(url_for('index'))

    # GET request (página inicial limpa)
    return render_template('index.html', download_ready=False)

@app.route('/download/<path:filename>')
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)