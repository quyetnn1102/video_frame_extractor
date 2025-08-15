"""
Database models for enhanced data management and analytics
Using SQLite for simplicity, can be easily upgraded to PostgreSQL
"""
import sqlite3
from datetime import datetime
from typing import Dict, Any
import json

from config import get_config
from logger import app_logger

class DatabaseManager:
    """Enhanced database management with connection pooling and migration support"""
    
    def __init__(self):
        self.config = get_config()
        self.db_path = self.config.BASE_DIR / 'app_data.db'
        self.init_database()
    
    def init_database(self):
        """Initialize database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Video processing requests table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS video_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url_hash TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        title TEXT,
                        duration INTEGER,
                        status TEXT DEFAULT 'pending',
                        error_message TEXT,
                        user_ip TEXT,
                        user_agent TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP,
                        processing_time_ms INTEGER
                    )
                ''')
                
                # Extracted frames table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS extracted_frames (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id INTEGER,
                        timestamp INTEGER NOT NULL,
                        filename TEXT NOT NULL,
                        file_size INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (request_id) REFERENCES video_requests (id)
                    )
                ''')
                
                # System statistics table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS system_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        metric_name TEXT NOT NULL,
                        metric_value REAL NOT NULL,
                        metadata TEXT,
                        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # User analytics table  
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_analytics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_ip TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        action TEXT NOT NULL,
                        success BOOLEAN DEFAULT 0,
                        response_time_ms INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create indexes for better performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_video_requests_platform ON video_requests(platform)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_video_requests_created_at ON video_requests(created_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_extracted_frames_request_id ON extracted_frames(request_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_analytics_platform ON user_analytics(platform)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_analytics_created_at ON user_analytics(created_at)')
                
                conn.commit()
                app_logger.info("Database initialized successfully")
                
        except Exception as e:
            app_logger.error(f"Database initialization failed: {str(e)}")
            raise
    
    def log_video_request(self, url_hash: str, platform: str, title: str = None, 
                         duration: int = None, user_ip: str = None, user_agent: str = None) -> int:
        """Log a new video processing request"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO video_requests (url_hash, platform, title, duration, user_ip, user_agent)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (url_hash, platform, title, duration, user_ip, user_agent))
                request_id = cursor.lastrowid
                conn.commit()
                return request_id
        except Exception as e:
            app_logger.error(f"Failed to log video request: {str(e)}")
            return 0
    
    def update_video_request(self, request_id: int, status: str, error_message: str = None, 
                           processing_time_ms: int = None):
        """Update video request status"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE video_requests 
                    SET status = ?, error_message = ?, processing_time_ms = ?, 
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, error_message, processing_time_ms, request_id))
                conn.commit()
        except Exception as e:
            app_logger.error(f"Failed to update video request: {str(e)}")
    
    def log_extracted_frame(self, request_id: int, timestamp: int, filename: str, file_size: int = None):
        """Log an extracted frame"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO extracted_frames (request_id, timestamp, filename, file_size)
                    VALUES (?, ?, ?, ?)
                ''', (request_id, timestamp, filename, file_size))
                conn.commit()
        except Exception as e:
            app_logger.error(f"Failed to log extracted frame: {str(e)}")
    
    def log_user_analytics(self, user_ip: str, platform: str, action: str, 
                          success: bool, response_time_ms: int = None):
        """Log user analytics data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_analytics (user_ip, platform, action, success, response_time_ms)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_ip, platform, action, success, response_time_ms))
                conn.commit()
        except Exception as e:
            app_logger.error(f"Failed to log user analytics: {str(e)}")
    
    def record_system_metric(self, metric_name: str, metric_value: float, metadata: Dict = None):
        """Record system performance metric"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                metadata_json = json.dumps(metadata) if metadata else None
                cursor.execute('''
                    INSERT INTO system_stats (metric_name, metric_value, metadata)
                    VALUES (?, ?, ?)
                ''', (metric_name, metric_value, metadata_json))
                conn.commit()
        except Exception as e:
            app_logger.error(f"Failed to record system metric: {str(e)}")
    
    def get_platform_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get platform usage statistics for the last N days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Platform usage stats
                cursor.execute('''
                    SELECT platform, 
                           COUNT(*) as total_requests,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_requests,
                           AVG(processing_time_ms) as avg_processing_time,
                           COUNT(DISTINCT user_ip) as unique_users
                    FROM video_requests
                    WHERE created_at >= datetime('now', '-{} days')
                    GROUP BY platform
                    ORDER BY total_requests DESC
                '''.format(days))
                
                platform_stats = []
                for row in cursor.fetchall():
                    platform_stats.append({
                        'platform': row[0],
                        'total_requests': row[1],
                        'successful_requests': row[2],
                        'success_rate': (row[2] / row[1] * 100) if row[1] > 0 else 0,
                        'avg_processing_time_ms': row[3] or 0,
                        'unique_users': row[4]
                    })
                
                # Total frames extracted
                cursor.execute('''
                    SELECT COUNT(*) FROM extracted_frames ef
                    JOIN video_requests vr ON ef.request_id = vr.id
                    WHERE vr.created_at >= datetime('now', '-{} days')
                '''.format(days))
                
                total_frames = cursor.fetchone()[0]
                
                return {
                    'period_days': days,
                    'platform_stats': platform_stats,
                    'total_frames_extracted': total_frames,
                    'generated_at': datetime.now().isoformat()
                }
                
        except Exception as e:
            app_logger.error(f"Failed to get platform statistics: {str(e)}")
            return {}
    
    def get_error_analysis(self, days: int = 7) -> Dict[str, Any]:
        """Get error analysis for troubleshooting"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT platform, error_message, COUNT(*) as error_count
                    FROM video_requests
                    WHERE status = 'failed' 
                      AND created_at >= datetime('now', '-{} days')
                      AND error_message IS NOT NULL
                    GROUP BY platform, error_message
                    ORDER BY error_count DESC
                    LIMIT 20
                '''.format(days))
                
                error_analysis = []
                for row in cursor.fetchall():
                    error_analysis.append({
                        'platform': row[0],
                        'error_message': row[1][:200] + '...' if len(row[1]) > 200 else row[1],
                        'error_count': row[2]
                    })
                
                return {
                    'period_days': days,
                    'error_analysis': error_analysis,
                    'generated_at': datetime.now().isoformat()
                }
                
        except Exception as e:
            app_logger.error(f"Failed to get error analysis: {str(e)}")
            return {}
    
    def cleanup_old_records(self, days: int = 30) -> int:
        """Clean up old database records"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Clean up old records
                cursor.execute('''
                    DELETE FROM user_analytics 
                    WHERE created_at < datetime('now', '-{} days')
                '''.format(days))
                
                cursor.execute('''
                    DELETE FROM system_stats 
                    WHERE recorded_at < datetime('now', '-{} days')
                '''.format(days))
                
                # Clean up old video requests and associated frames
                cursor.execute('''
                    DELETE FROM extracted_frames 
                    WHERE request_id IN (
                        SELECT id FROM video_requests 
                        WHERE created_at < datetime('now', '-{} days')
                    )
                '''.format(days))
                
                cursor.execute('''
                    DELETE FROM video_requests 
                    WHERE created_at < datetime('now', '-{} days')
                '''.format(days))
                
                deleted_records = cursor.rowcount
                conn.commit()
                
                # Vacuum database to reclaim space
                cursor.execute('VACUUM')
                
                return deleted_records
                
        except Exception as e:
            app_logger.error(f"Failed to cleanup old records: {str(e)}")
            return 0

# Global database manager instance
db_manager = DatabaseManager()

def get_analytics() -> Dict[str, Any]:
    """Get comprehensive analytics data"""
    try:
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            
            # Total requests
            cursor.execute('SELECT COUNT(*) FROM video_requests')
            total_requests = cursor.fetchone()[0]
            
            # Successful requests
            cursor.execute("SELECT COUNT(*) FROM video_requests WHERE status = 'completed'")
            successful_requests = cursor.fetchone()[0]
            
            # Platform breakdown
            cursor.execute('''
                SELECT platform, COUNT(*) as count 
                FROM video_requests 
                GROUP BY platform 
                ORDER BY count DESC
            ''')
            platform_stats = dict(cursor.fetchall())
            
            # Recent activity (last 24 hours)
            cursor.execute('''
                SELECT COUNT(*) FROM video_requests 
                WHERE created_at >= datetime('now', '-1 day')
            ''')
            recent_requests = cursor.fetchone()[0]
            
            # Average processing time
            cursor.execute('''
                SELECT AVG(processing_time_ms) FROM video_requests 
                WHERE processing_time_ms IS NOT NULL
            ''')
            avg_processing_time = cursor.fetchone()[0] or 0
            
            # Total frames extracted
            cursor.execute('SELECT COUNT(*) FROM extracted_frames')
            total_frames = cursor.fetchone()[0]
            
            return {
                'total_requests': total_requests,
                'successful_requests': successful_requests,
                'success_rate': (successful_requests / total_requests * 100) if total_requests > 0 else 0,
                'platform_stats': platform_stats,
                'recent_requests_24h': recent_requests,
                'avg_processing_time_ms': round(avg_processing_time, 2),
                'total_frames_extracted': total_frames
            }
            
    except Exception as e:
        app_logger.error(f"Failed to get analytics: {str(e)}")
        return {
            'total_requests': 0,
            'successful_requests': 0,
            'success_rate': 0,
            'platform_stats': {},
            'recent_requests_24h': 0,
            'avg_processing_time_ms': 0,
            'total_frames_extracted': 0
        }

def get_recent_requests(limit: int = 10) -> list:
    """Get recent video processing requests"""
    try:
        with sqlite3.connect(db_manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT platform, title, status, created_at, processing_time_ms, user_ip
                FROM video_requests 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            return [{
                'platform': row[0],
                'title': row[1] or 'Unknown',
                'status': row[2],
                'created_at': row[3],
                'processing_time_ms': row[4],
                'user_ip': row[5]
            } for row in rows]
            
    except Exception as e:
        app_logger.error(f"Failed to get recent requests: {str(e)}")
        return []
