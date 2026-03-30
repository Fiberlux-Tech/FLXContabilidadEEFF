import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:5000")
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")
worker_connections = int(os.environ.get("GUNICORN_WORKER_CONNECTIONS", "1000"))
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "50"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", os.path.join(log_dir, "access.log"))
errorlog = os.environ.get("GUNICORN_ERROR_LOG", os.path.join(log_dir, "error.log"))
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True

proc_name = "flxcontabilidad"
daemon = False
