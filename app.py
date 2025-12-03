import os
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.secret_key = 'vibe_key_secret_123'

# Pasta onde a música fica temporariamente
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url')
        if not url:
            flash('Cole um link válido!', 'error')
            return redirect(url_for('index'))

        try:
            # Configuração para baixar MP3 com qualidade
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
            }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # O nome do arquivo muda para .mp3 após a conversão
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            
            return send_file(filename, as_attachment=True)

        except Exception as e:
            flash(f'Erro: {str(e)}', 'error')
            return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5002)