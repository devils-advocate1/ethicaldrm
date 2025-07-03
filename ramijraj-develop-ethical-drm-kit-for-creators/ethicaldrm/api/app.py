"""
Flask REST API for EthicalDRM

Provides HTTP endpoints for:
- Video watermarking and verification
- Leak detection and scanning
- Screen recording monitoring
- Results management and reporting
"""

from flask import Flask, request, jsonify, send_file
import os
import logging
import asyncio
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional
import sqlite3
from pathlib import Path
import json

from ..video.watermark import Watermarker
from ..leakbot.scanner import LeakScanner
from ..recorder.detect import ScreenRecorderDetector

logger = logging.getLogger(__name__)


class EthicalDRMAPI:
    """Main API class for EthicalDRM REST endpoints."""
    
    def __init__(self, app: Flask):
        self.app = app
        self.db_path = "ethicaldrm.db"
        self.upload_folder = "uploads"
        self.output_folder = "outputs"
        
        # Initialize folders
        os.makedirs(self.upload_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        # Active sessions
        self.active_scanners = {}
        self.active_detectors = {}
        
        # Register routes
        self._register_routes()
    
    def _init_database(self):
        """Initialize SQLite database for logging and tracking."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Watermarking sessions table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS watermark_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        input_file TEXT NOT NULL,
                        output_file TEXT NOT NULL,
                        watermark_signature TEXT,
                        method TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        status TEXT,
                        metadata TEXT
                    )
                ''')
                
                # Leak detections table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS leak_detections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_content TEXT NOT NULL,
                        platform TEXT,
                        source_url TEXT,
                        similarity_score REAL,
                        status TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        metadata TEXT
                    )
                ''')
                
                # Screen recording events table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS recording_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        process_name TEXT,
                        process_id INTEGER,
                        detection_method TEXT,
                        severity TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        action_taken TEXT
                    )
                ''')
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except Exception as e:
            logger.error(f"Database initialization failed: {str(e)}")
    
    def _register_routes(self):
        """Register all API routes."""
        
        # Health check
        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                'status': 'healthy',
                'version': '1.0.0',
                'timestamp': datetime.now().isoformat()
            })
        
        # Watermarking endpoints
        @self.app.route('/watermark/embed', methods=['POST'])
        def embed_watermark():
            return self._embed_watermark()
        
        @self.app.route('/watermark/extract', methods=['POST'])
        def extract_watermark():
            return self._extract_watermark()
        
        @self.app.route('/watermark/verify', methods=['POST'])
        def verify_watermark():
            return self._verify_watermark()
        
        # Leak detection endpoints
        @self.app.route('/scanner/create', methods=['POST'])
        def create_scanner():
            return self._create_scanner()
        
        @self.app.route('/scanner/scan', methods=['POST'])
        def run_scan():
            return self._run_scan()
        
        @self.app.route('/scanner/results/<scanner_id>', methods=['GET'])
        def get_scan_results(scanner_id):
            return self._get_scan_results(scanner_id)
        
        @self.app.route('/scanner/configure/<scanner_id>', methods=['POST'])
        def configure_scanner(scanner_id):
            return self._configure_scanner(scanner_id)
        
        # Screen recording detection endpoints
        @self.app.route('/detector/start', methods=['POST'])
        def start_detection():
            return self._start_detection()
        
        @self.app.route('/detector/stop/<detector_id>', methods=['POST'])
        def stop_detection(detector_id):
            return self._stop_detection(detector_id)
        
        @self.app.route('/detector/status/<detector_id>', methods=['GET'])
        def get_detection_status(detector_id):
            return self._get_detection_status(detector_id)
        
        # Reporting endpoints
        @self.app.route('/reports/watermarks', methods=['GET'])
        def get_watermark_reports():
            return self._get_watermark_reports()
        
        @self.app.route('/reports/detections', methods=['GET'])
        def get_detection_reports():
            return self._get_detection_reports()
        
        @self.app.route('/reports/export', methods=['POST'])
        def export_reports():
            return self._export_reports()
    
    def _embed_watermark(self):
        """Embed watermark in uploaded video."""
        try:
            # Get parameters
            user_id = request.form.get('user_id')
            method = request.form.get('method', 'lsb')
            strength = float(request.form.get('strength', 0.1))
            
            if not user_id:
                return jsonify({'error': 'user_id is required'}), 400
            
            # Handle file upload
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # Save uploaded file
            input_path = os.path.join(self.upload_folder, f"{user_id}_{int(time.time())}_{file.filename}")
            file.save(input_path)
            
            # Generate output path
            output_filename = f"watermarked_{user_id}_{int(time.time())}.mp4"
            output_path = os.path.join(self.output_folder, output_filename)
            
            # Create watermarker and embed
            watermarker = Watermarker(user_id, method, strength)
            result = watermarker.embed(input_path, output_path)
            
            if result['success']:
                # Save to database
                self._save_watermark_session(
                    user_id=user_id,
                    input_file=input_path,
                    output_file=output_path,
                    watermark_signature=result['signature'],
                    method=method,
                    status='completed',
                    metadata=json.dumps(result)
                )
                
                return jsonify({
                    'success': True,
                    'output_file': output_filename,
                    'watermark_signature': result['signature'],
                    'download_url': f'/download/{output_filename}',
                    'statistics': {
                        'total_frames': result['total_frames'],
                        'watermarked_frames': result['watermarked_frames'],
                        'file_size': result['file_size']
                    }
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Watermarking failed')
                }), 500
                
        except Exception as e:
            logger.error(f"Watermark embedding failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _extract_watermark(self):
        """Extract watermark from uploaded video."""
        try:
            # Handle file upload
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # Save uploaded file
            input_path = os.path.join(self.upload_folder, f"extract_{int(time.time())}_{file.filename}")
            file.save(input_path)
            
            # Create watermarker and extract
            watermarker = Watermarker("temp")  # Temporary instance for extraction
            watermark_data = watermarker.extract_watermark(input_path)
            
            # Clean up uploaded file
            os.remove(input_path)
            
            if watermark_data:
                return jsonify({
                    'success': True,
                    'watermark_found': True,
                    'user_id': watermark_data.get('user_id'),
                    'signature': watermark_data.get('signature'),
                    'frame_number': watermark_data.get('frame_number'),
                    'extracted_text': watermark_data.get('extracted_text')
                })
            else:
                return jsonify({
                    'success': True,
                    'watermark_found': False,
                    'message': 'No watermark detected in the uploaded file'
                })
                
        except Exception as e:
            logger.error(f"Watermark extraction failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _verify_watermark(self):
        """Verify watermark integrity for specific user."""
        try:
            user_id = request.form.get('user_id')
            if not user_id:
                return jsonify({'error': 'user_id is required'}), 400
            
            # Handle file upload
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
            
            file = request.files['file']
            input_path = os.path.join(self.upload_folder, f"verify_{int(time.time())}_{file.filename}")
            file.save(input_path)
            
            # Create watermarker and verify
            watermarker = Watermarker(user_id)
            verification_result = watermarker.verify_integrity(input_path)
            
            # Clean up
            os.remove(input_path)
            
            return jsonify({
                'success': True,
                'verification_result': verification_result
            })
            
        except Exception as e:
            logger.error(f"Watermark verification failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _create_scanner(self):
        """Create new leak scanner instance."""
        try:
            data = request.get_json()
            
            original_content_path = data.get('original_content_path')
            similarity_threshold = data.get('similarity_threshold', 0.85)
            scan_interval_hours = data.get('scan_interval_hours', 24)
            
            if not original_content_path:
                return jsonify({'error': 'original_content_path is required'}), 400
            
            # Create scanner
            scanner = LeakScanner(
                original_content_path=original_content_path,
                similarity_threshold=similarity_threshold,
                scan_interval_hours=scan_interval_hours
            )
            
            # Generate scanner ID
            scanner_id = f"scanner_{int(time.time())}"
            self.active_scanners[scanner_id] = scanner
            
            return jsonify({
                'success': True,
                'scanner_id': scanner_id,
                'original_content_path': original_content_path,
                'similarity_threshold': similarity_threshold,
                'reference_hashes_count': len(scanner.reference_hashes)
            })
            
        except Exception as e:
            logger.error(f"Scanner creation failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _run_scan(self):
        """Run leak scan for specified scanner."""
        try:
            data = request.get_json()
            scanner_id = data.get('scanner_id')
            
            if not scanner_id or scanner_id not in self.active_scanners:
                return jsonify({'error': 'Invalid scanner_id'}), 400
            
            scanner = self.active_scanners[scanner_id]
            
            # Run scan asynchronously
            def run_async_scan():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(scanner.run_full_scan())
                    
                    # Save detections to database
                    for detection in result.get('detections', []):
                        self._save_leak_detection(
                            original_content=scanner.original_content_path,
                            platform=detection.get('platform'),
                            source_url=detection.get('url'),
                            similarity_score=detection.get('similarity_score'),
                            status=detection.get('status'),
                            metadata=json.dumps(detection)
                        )
                finally:
                    loop.close()
            
            # Start scan in background thread
            threading.Thread(target=run_async_scan, daemon=True).start()
            
            return jsonify({
                'success': True,
                'message': 'Scan started',
                'scanner_id': scanner_id
            })
            
        except Exception as e:
            logger.error(f"Scan execution failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _get_scan_results(self, scanner_id: str):
        """Get scan results for specified scanner."""
        try:
            if scanner_id not in self.active_scanners:
                return jsonify({'error': 'Invalid scanner_id'}), 400
            
            scanner = self.active_scanners[scanner_id]
            scan_history = scanner.get_scan_history()
            
            return jsonify({
                'success': True,
                'scanner_id': scanner_id,
                'scan_history': scan_history,
                'total_scans': len(scan_history)
            })
            
        except Exception as e:
            logger.error(f"Getting scan results failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _configure_scanner(self, scanner_id: str):
        """Configure scanner platform settings."""
        try:
            if scanner_id not in self.active_scanners:
                return jsonify({'error': 'Invalid scanner_id'}), 400
            
            data = request.get_json()
            platform = data.get('platform')
            config = data.get('config')
            
            if not platform or not config:
                return jsonify({'error': 'platform and config are required'}), 400
            
            scanner = self.active_scanners[scanner_id]
            scanner.configure_platform(platform, config)
            
            return jsonify({
                'success': True,
                'message': f'Platform {platform} configured successfully'
            })
            
        except Exception as e:
            logger.error(f"Scanner configuration failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _start_detection(self):
        """Start screen recording detection."""
        try:
            data = request.get_json()
            check_interval = data.get('check_interval', 2.0)
            strict_mode = data.get('strict_mode', False)
            
            # Create detector with callback
            def on_detection_callback(detected_recorders):
                for recorder in detected_recorders:
                    self._save_recording_event(
                        process_name=recorder.get('name'),
                        process_id=recorder.get('pid'),
                        detection_method=recorder.get('recorder_type'),
                        severity=recorder.get('severity'),
                        action_taken='detected'
                    )
            
            detector = ScreenRecorderDetector(
                check_interval=check_interval,
                on_detection=on_detection_callback,
                strict_mode=strict_mode
            )
            
            # Start monitoring
            success = detector.start_monitoring()
            
            if success:
                # Generate detector ID
                detector_id = f"detector_{int(time.time())}"
                self.active_detectors[detector_id] = detector
                
                return jsonify({
                    'success': True,
                    'detector_id': detector_id,
                    'monitoring_active': True,
                    'check_interval': check_interval,
                    'strict_mode': strict_mode
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to start monitoring'
                }), 500
                
        except Exception as e:
            logger.error(f"Detection start failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _stop_detection(self, detector_id: str):
        """Stop screen recording detection."""
        try:
            if detector_id not in self.active_detectors:
                return jsonify({'error': 'Invalid detector_id'}), 400
            
            detector = self.active_detectors[detector_id]
            detector.stop_monitoring()
            
            # Remove from active detectors
            del self.active_detectors[detector_id]
            
            return jsonify({
                'success': True,
                'message': 'Detection stopped',
                'detector_id': detector_id
            })
            
        except Exception as e:
            logger.error(f"Detection stop failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _get_detection_status(self, detector_id: str):
        """Get detection status and statistics."""
        try:
            if detector_id not in self.active_detectors:
                return jsonify({'error': 'Invalid detector_id'}), 400
            
            detector = self.active_detectors[detector_id]
            status = detector.get_detection_status()
            
            return jsonify({
                'success': True,
                'detector_id': detector_id,
                'status': status
            })
            
        except Exception as e:
            logger.error(f"Getting detection status failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _get_watermark_reports(self):
        """Get watermarking session reports."""
        try:
            limit = request.args.get('limit', 100, type=int)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM watermark_sessions 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,))
                
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                sessions = [dict(zip(columns, row)) for row in rows]
            
            return jsonify({
                'success': True,
                'watermark_sessions': sessions,
                'total_count': len(sessions)
            })
            
        except Exception as e:
            logger.error(f"Getting watermark reports failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _get_detection_reports(self):
        """Get leak detection reports."""
        try:
            limit = request.args.get('limit', 100, type=int)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM leak_detections 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,))
                
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                detections = [dict(zip(columns, row)) for row in rows]
            
            return jsonify({
                'success': True,
                'leak_detections': detections,
                'total_count': len(detections)
            })
            
        except Exception as e:
            logger.error(f"Getting detection reports failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _export_reports(self):
        """Export reports to file."""
        try:
            data = request.get_json()
            report_type = data.get('report_type', 'all')
            format_type = data.get('format', 'json')
            
            output_filename = f"ethicaldrm_report_{int(time.time())}.{format_type}"
            output_path = os.path.join(self.output_folder, output_filename)
            
            if format_type == 'json':
                report_data = {}
                
                if report_type in ['all', 'watermarks']:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT * FROM watermark_sessions')
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        report_data['watermark_sessions'] = [dict(zip(columns, row)) for row in rows]
                
                if report_type in ['all', 'detections']:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT * FROM leak_detections')
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        report_data['leak_detections'] = [dict(zip(columns, row)) for row in rows]
                
                if report_type in ['all', 'recordings']:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT * FROM recording_events')
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        report_data['recording_events'] = [dict(zip(columns, row)) for row in rows]
                
                with open(output_path, 'w') as f:
                    json.dump(report_data, f, indent=2)
            
            return jsonify({
                'success': True,
                'output_file': output_filename,
                'download_url': f'/download/{output_filename}'
            })
            
        except Exception as e:
            logger.error(f"Report export failed: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def _save_watermark_session(self, user_id: str, input_file: str, output_file: str,
                               watermark_signature: str, method: str, status: str, metadata: str):
        """Save watermarking session to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO watermark_sessions 
                    (user_id, input_file, output_file, watermark_signature, method, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, input_file, output_file, watermark_signature, method, status, metadata))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save watermark session: {str(e)}")
    
    def _save_leak_detection(self, original_content: str, platform: str, source_url: str,
                            similarity_score: float, status: str, metadata: str):
        """Save leak detection to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO leak_detections 
                    (original_content, platform, source_url, similarity_score, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (original_content, platform, source_url, similarity_score, status, metadata))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save leak detection: {str(e)}")
    
    def _save_recording_event(self, process_name: str, process_id: int, detection_method: str,
                             severity: str, action_taken: str):
        """Save recording event to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO recording_events 
                    (process_name, process_id, detection_method, severity, action_taken)
                    VALUES (?, ?, ?, ?, ?)
                ''', (process_name, process_id, detection_method, severity, action_taken))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save recording event: {str(e)}")


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Create and configure Flask application for EthicalDRM API.
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    
    # Default configuration
    app.config.update({
        'MAX_CONTENT_LENGTH': 500 * 1024 * 1024,  # 500MB max upload
        'UPLOAD_FOLDER': 'uploads',
        'SECRET_KEY': 'ethicaldrm-secret-key-change-in-production'
    })
    
    # Update with custom config
    if config:
        app.config.update(config)
    
    # Initialize API
    api = EthicalDRMAPI(app)
    
    # File download endpoint
    @app.route('/download/<filename>')
    def download_file(filename):
        try:
            file_path = os.path.join(api.output_folder, filename)
            if os.path.exists(file_path):
                return send_file(file_path, as_attachment=True)
            else:
                return jsonify({'error': 'File not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # Error handlers
    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({'error': 'File too large'}), 413
    
    @app.errorhandler(500)
    def internal_server_error(error):
        return jsonify({'error': 'Internal server error'}), 500
    
    logger.info("EthicalDRM API initialized successfully")
    
    return app


if __name__ == '__main__':
    # Development server
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)