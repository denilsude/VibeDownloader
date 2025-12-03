import os
import zipfile
import time
import matplotlib
matplotlib.use('Agg') # Backend não-interativo para servidor
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

# Garante que as pastas existem
for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def limpar_pastas():
    """Remove arquivos da execução anterior para não lotar o disco"""
    for folder in [DOWNLOAD_FOLDER, STATIC_FOLDER]:
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Erro ao limpar {file_path}: {e}")

def gerar_spek_visual(audio_path, title):
    """
    Simula o visual do software Spek usando Librosa e Matplotlib.
    Fundo preto, cores vibrantes, eixo de frequências logarítmico.
    """
    try:
        # Carrega o áudio (apenas os primeiros 120s para performance)
        y, sr = librosa.load(audio_path, duration=120)
        
        # Configura o estilo visual "Dark Spek"
        plt.style.use('dark_background')
        plt.figure(figsize=(12, 4))
        
        # Gera o espectrograma
        D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
        
        # Desenha usando colormap 'inferno' ou 'nipy_spectral' (parecido com Spek)
        librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='hz', cmap='inferno')
        
        plt.colorbar(format='%+2.0f dB')
        plt.title(f'Análise Espectral: {title}', color='white')
        plt.xlabel('Tempo', color='gray')
        plt.ylabel('Frequência (Hz)', color='gray')
        plt.tight_layout()
        
        # Salva imagem
        clean_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).rstrip()
        image_filename = f"spek_{clean_title}_{int(time.time())}.png"
        image_path = os.path.join(STATIC_FOLDER, image_filename)
        plt.savefig(image_path, facecolor='black')
        plt.close()
        
        return image_filename
    except Exception as e:
        print(f"Erro no Spek: {e}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        limpar_pastas()
        
        # Pega a lista de URLs do formulário dinâmico
        urls = request.form.getlist('urls[]')
        format_type = request.form.get('format')
        
        # Filtra URLs vazias
        urls = [u for u in urls if u.strip()]
        
        if not urls:
            flash('Nenhum link fornecido.', 'error')
            return redirect(url_for('index'))

        results_data = [] # Lista para armazenar dados de cada música processada
        downloaded_files = []

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_type,
                'preferredquality': '320' if format_type == 'mp3' else None,
            }],
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    try:
                        info = ydl.extract_info(url, download=True)
                        filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{format_type}'
                        title = info.get('title', 'Unknown Track')
                        
                        # Gera o gráfico Spek
                        spec_img = gerar_spek_visual(filename, title)
                        
                        results_data.append({
                            'title': title,
                            'format': format_type,
                            'spectrogram': spec_img
                        })
                        downloaded_files.append(filename)
                    except Exception as e:
                        print(f"Erro ao baixar {url}: {e}")
                        continue

            if not downloaded_files:
                flash('Falha ao processar os links.', 'error')
                return redirect(url_for('index'))

            # Cria o ZIP final com todas as músicas
            zip_name = f"VibePack_{int(time.time())}.zip"
            zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in downloaded_files:
                    zipf.write(file, os.path.basename(file))
            
            # Renderiza a página com os gráficos e o botão de download
            return render_template('index.html', results=results_data, zip_name=zip_name)

        except Exception as e:
            flash(f'Erro crítico: {str(e)}', 'error')
            return redirect(url_for('index'))

    return render_template('index.html', results=None)

@app.route('/download/<path:filename>')
def download_zip(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5002)