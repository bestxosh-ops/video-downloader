from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import threading
import time
from urllib.parse import urlparse
import requests
import json

app = Flask(__name__)
CORS(app)

# Create downloads directory
DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class VideoDownloader:
    def __init__(self):
        self.downloads = {}
    
    def get_video_info(self, url):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                formats = []
                if 'formats' in info:
                    for f in info['formats']:
                        if f.get('vcodec') != 'none':
                            quality = f.get('height', 'Unknown')
                            formats.append({
                                'format_id': f['format_id'],
                                'quality': f"{quality}p" if quality != 'Unknown' else 'Unknown',
                                'ext': f.get('ext', 'mp4'),
                                'filesize': f.get('filesize')
                            })
                
                unique_formats = []
                seen_qualities = set()
                for fmt in sorted(formats, key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].replace('p', '').isdigit() else 0, reverse=True):
                    if fmt['quality'] not in seen_qualities:
                        unique_formats.append(fmt)
                        seen_qualities.add(fmt['quality'])
                
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'uploader': info.get('uploader'),
                    'formats': unique_formats[:5]
                }
        except Exception as e:
            raise Exception(f"Could not extract video info: {str(e)}")
    
    def download_video(self, url, format_id=None, download_id=None):
        try:
            filename = f"video_{download_id}_{int(time.time())}"
            output_path = os.path.join(DOWNLOAD_DIR, f"{filename}.%(ext)s")
            
            ydl_opts = {
                'format': format_id if format_id else 'best',
                'outtmpl': output_path,
                'quiet': True,
            }
            
            def progress_hook(d):
                if download_id and download_id in self.downloads:
                    if d['status'] == 'downloading':
                        self.downloads[download_id]['progress'] = d.get('_percent_str', '0%')
                        self.downloads[download_id]['speed'] = d.get('_speed_str', 'N/A')
                    elif d['status'] == 'finished':
                        self.downloads[download_id]['status'] = 'completed'
                        self.downloads[download_id]['file_path'] = d['filename']
            
            ydl_opts['progress_hooks'] = [progress_hook]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            return True
            
        except Exception as e:
            if download_id:
                self.downloads[download_id]['status'] = 'error'
                self.downloads[download_id]['error'] = str(e)
            raise Exception(f"Download failed: {str(e)}")

downloader = VideoDownloader()

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        parsed_url = urlparse(url)
        if not parsed_url.netloc:
            return jsonify({'error': 'Invalid URL'}), 400
        
        video_info = downloader.get_video_info(url)
        
        return jsonify({
            'success': True,
            'data': video_info
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        download_id = f"dl_{int(time.time())}_{hash(url) % 10000}"
        
        downloader.downloads[download_id] = {
            'status': 'starting',
            'progress': '0%',
            'speed': 'N/A',
            'url': url,
            'format_id': format_id
        }
        
        thread = threading.Thread(
            target=downloader.download_video,
            args=(url, format_id, download_id)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'download_id': download_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/progress/<download_id>', methods=['GET'])
def get_progress(download_id):
    if download_id not in downloader.downloads:
        return jsonify({'error': 'Download not found'}), 404
    
    return jsonify({
        'success': True,
        'data': downloader.downloads[download_id]
    })

@app.route('/api/download/<download_id>', methods=['GET'])
def get_file(download_id):
    if download_id not in downloader.downloads:
        return jsonify({'error': 'Download not found'}), 404
    
    download_info = downloader.downloads[download_id]
    
    if download_info['status'] != 'completed':
        return jsonify({'error': 'Download not completed'}), 400
    
    file_path = download_info.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(file_path)
    )

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'video-downloader'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
