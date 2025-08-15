"""
Performance monitoring and analytics dashboard
Provides real-time insights into application performance
"""
from flask import jsonify, render_template_string
from datetime import datetime
from typing import Dict, Any

from config import get_config
from logger import app_logger
from database import db_manager

class PerformanceMonitor:
    """Monitor system and application performance"""
    
    def __init__(self):
        self.config = get_config()
        self.start_time = datetime.now()
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system performance metrics"""
        try:
            # Simple system metrics without psutil dependency
            import shutil
            
            # Get disk usage for current directory
            total, used, free = shutil.disk_usage('.')
            disk_percent = (used / total) * 100 if total > 0 else 0
            
            return {
                'cpu_percent': 0.0,  # Would require psutil
                'memory_percent': 0.0,  # Would require psutil
                'disk_usage': {
                    'total': total,
                    'used': used,
                    'free': free,
                    'percent': disk_percent
                },
                'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            app_logger.error(f"Failed to get system metrics: {str(e)}")
            return {'error': str(e)}
    
    def get_application_metrics(self) -> Dict[str, Any]:
        """Get application-specific performance metrics"""
        try:
            # Get recent statistics from database
            stats = db_manager.get_platform_statistics(days=7)
            error_analysis = db_manager.get_error_analysis(days=7)
            
            # Calculate folder sizes
            folder_sizes = {}
            for folder_name in ['DOWNLOAD_FOLDER', 'FRAMES_FOLDER', 'SHORTS_FOLDER']:
                folder_path = getattr(self.config, folder_name)
                size_mb = self._get_folder_size_mb(folder_path)
                folder_sizes[folder_name.lower()] = size_mb
            
            return {
                'platform_statistics': stats,
                'error_analysis': error_analysis,
                'folder_sizes_mb': folder_sizes,
                'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            app_logger.error(f"Failed to get application metrics: {str(e)}")
            return {'error': str(e)}
    
    def _get_folder_size_mb(self, folder_path) -> float:
        """Calculate folder size in MB"""
        try:
            total_size = 0
            if folder_path.exists():
                for file_path in folder_path.rglob('*'):
                    if file_path.is_file():
                        total_size += file_path.stat().st_size
            return round(total_size / (1024 * 1024), 2)
        except Exception:
            return 0.0
    
    def record_performance_metrics(self):
        """Record current metrics to database"""
        try:
            system_metrics = self.get_system_metrics()
            
            # Record key metrics
            metrics_to_record = [
                ('cpu_percent', system_metrics.get('cpu_percent', 0)),
                ('memory_percent', system_metrics.get('memory_percent', 0)),
                ('disk_usage_percent', system_metrics.get('disk_usage', {}).get('percent', 0))
            ]
            
            for metric_name, value in metrics_to_record:
                if isinstance(value, (int, float)):
                    db_manager.record_system_metric(metric_name, value)
            
        except Exception as e:
            app_logger.error(f"Failed to record performance metrics: {str(e)}")

def create_analytics_routes(app):
    """Add analytics routes to Flask app"""
    
    monitor = PerformanceMonitor()
    
    @app.route('/api/analytics/system')
    def system_metrics():
        """Get system performance metrics"""
        return jsonify(monitor.get_system_metrics())
    
    @app.route('/api/analytics/application')
    def application_metrics():
        """Get application performance metrics"""
        return jsonify(monitor.get_application_metrics())
    
    @app.route('/api/analytics/dashboard')
    def analytics_dashboard():
        """Combined dashboard data"""
        system_data = monitor.get_system_metrics()
        app_data = monitor.get_application_metrics()
        
        return jsonify({
            'system': system_data,
            'application': app_data,
            'generated_at': datetime.now().isoformat()
        })
    
    @app.route('/dashboard')
    def dashboard():
        """Analytics dashboard page"""
        dashboard_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Frame Extractor - Analytics Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .dashboard {
            max-width: 1400px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
        }
        
        .dashboard-header {
            text-align: center;
            margin-bottom: 40px;
        }
        
        .dashboard-header h1 {
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .metric-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            border-left: 5px solid #667eea;
        }
        
        .metric-card h3 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.2em;
        }
        
        .metric-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .metric-label {
            color: #666;
            font-size: 0.9em;
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        
        .status-good { background-color: #4caf50; }
        .status-warning { background-color: #ff9800; }
        .status-error { background-color: #f44336; }
        
        .platform-stats {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
            margin-bottom: 20px;
        }
        
        .platform-stats h3 {
            color: #333;
            margin-bottom: 20px;
        }
        
        .platform-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        
        .platform-name {
            font-weight: 600;
            text-transform: capitalize;
        }
        
        .platform-metrics {
            display: flex;
            gap: 20px;
            font-size: 0.9em;
            color: #666;
        }
        
        .refresh-btn {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 25px;
            padding: 12px 24px;
            cursor: pointer;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }
        
        .refresh-btn:hover {
            background: #5a6fd8;
        }
        
        .loading {
            text-align: center;
            color: #666;
            font-style: italic;
            padding: 20px;
        }
        
        .error {
            background: #ffebee;
            color: #c62828;
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <button class="refresh-btn" onclick="loadDashboard()">🔄 Refresh</button>
    
    <div class="dashboard">
        <div class="dashboard-header">
            <h1>📊 Analytics Dashboard</h1>
            <p>Real-time system and application performance metrics</p>
        </div>
        
        <div id="dashboard-content">
            <div class="loading">Loading dashboard data...</div>
        </div>
    </div>

    <script>
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
        
        function formatUptime(seconds) {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${hours}h ${minutes}m`;
        }
        
        function getStatusClass(percent) {
            if (percent < 60) return 'status-good';
            if (percent < 80) return 'status-warning';
            return 'status-error';
        }
        
        function renderDashboard(data) {
            const container = document.getElementById('dashboard-content');
            const system = data.system;
            const app = data.application;
            
            container.innerHTML = `
                <div class="metrics-grid">
                    <div class="metric-card">
                        <h3><span class="status-indicator ${getStatusClass(system.cpu_percent)}"></span>CPU Usage</h3>
                        <div class="metric-value">${system.cpu_percent?.toFixed(1) || 'N/A'}%</div>
                        <div class="metric-label">Processor utilization</div>
                    </div>
                    
                    <div class="metric-card">
                        <h3><span class="status-indicator ${getStatusClass(system.memory_percent)}"></span>Memory Usage</h3>
                        <div class="metric-value">${system.memory_percent?.toFixed(1) || 'N/A'}%</div>
                        <div class="metric-label">RAM utilization</div>
                    </div>
                    
                    <div class="metric-card">
                        <h3><span class="status-indicator ${getStatusClass(system.disk_usage?.percent || 0)}"></span>Disk Usage</h3>
                        <div class="metric-value">${system.disk_usage?.percent?.toFixed(1) || 'N/A'}%</div>
                        <div class="metric-label">${formatBytes(system.disk_usage?.used || 0)} used</div>
                    </div>
                    
                    <div class="metric-card">
                        <h3><span class="status-indicator status-good"></span>Uptime</h3>
                        <div class="metric-value">${formatUptime(system.uptime_seconds || 0)}</div>
                        <div class="metric-label">System uptime</div>
                    </div>
                    
                    <div class="metric-card">
                        <h3><span class="status-indicator status-good"></span>Total Requests</h3>
                        <div class="metric-value">${app.platform_statistics?.platform_stats?.reduce((sum, p) => sum + p.total_requests, 0) || 0}</div>
                        <div class="metric-label">Last 7 days</div>
                    </div>
                    
                    <div class="metric-card">
                        <h3><span class="status-indicator status-good"></span>Frames Extracted</h3>
                        <div class="metric-value">${app.platform_statistics?.total_frames_extracted || 0}</div>
                        <div class="metric-label">Last 7 days</div>
                    </div>
                </div>
                
                <div class="platform-stats">
                    <h3>📱 Platform Performance (Last 7 Days)</h3>
                    ${app.platform_statistics?.platform_stats?.map(platform => `
                        <div class="platform-item">
                            <div class="platform-name">${platform.platform}</div>
                            <div class="platform-metrics">
                                <span>📊 ${platform.total_requests} requests</span>
                                <span>✅ ${platform.success_rate.toFixed(1)}% success</span>
                                <span>⏱️ ${(platform.avg_processing_time_ms || 0).toFixed(0)}ms avg</span>
                                <span>👥 ${platform.unique_users} users</span>
                            </div>
                        </div>
                    `).join('') || '<div class="loading">No platform data available</div>'}
                </div>
                
                <div class="platform-stats">
                    <h3>💾 Storage Usage</h3>
                    ${Object.entries(app.folder_sizes_mb || {}).map(([folder, size]) => `
                        <div class="platform-item">
                            <div class="platform-name">${folder.replace('_folder', '').replace('_', ' ')}</div>
                            <div class="platform-metrics">
                                <span>${size} MB</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
                
                <div style="text-align: center; margin-top: 30px; color: #666; font-size: 0.9em;">
                    Last updated: ${new Date(data.generated_at).toLocaleString()}
                </div>
            `;
        }
        
        function showError(message) {
            document.getElementById('dashboard-content').innerHTML = `
                <div class="error">
                    ❌ Error loading dashboard: ${message}
                </div>
            `;
        }
        
        async function loadDashboard() {
            try {
                document.getElementById('dashboard-content').innerHTML = '<div class="loading">Loading dashboard data...</div>';
                
                const response = await fetch('/api/analytics/dashboard');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                
                const data = await response.json();
                renderDashboard(data);
                
            } catch (error) {
                console.error('Dashboard error:', error);
                showError(error.message);
            }
        }
        
        // Load dashboard on page load
        loadDashboard();
        
        // Auto-refresh every 30 seconds
        setInterval(loadDashboard, 30000);
    </script>
</body>
</html>
        '''
        return render_template_string(dashboard_html)
