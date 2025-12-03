import os
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.secret_key = 'vibe_key_secret_123'

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url')
        format_type = request.form.get('format')  # Pega a escolha: 'mp3' ou 'wav'

        if not url:
            return redirect(url_for('index'))

        try:
            # Configuração dinâmica baseada na escolha do usuário
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format_type,  # Usa 'mp3' ou 'wav' dinamicamente
                    'preferredquality': '192',
                }],
            }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # O nome do arquivo final depende da conversão
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + f'.{format_type}'
            
            return send_file(filename, as_attachment=True)

        except Exception as e:
            flash(f'Erro: {str(e)}', 'error')
            return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5002)