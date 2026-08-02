# CCPanel — container image.
#
# Backend + frontend build dalam satu image. Jalan sebagai root di dalam
# container (akses nginx/mysql/certbot di host TIDAK tersedia dari sini —
# mode ini untuk panel standalone: nginx + mariadb + php-fpm di dalam image).
#
# Build:
#   docker build -t ccpanel .
# Run (panel + nginx + mariadb sekaligus, bind panel 8888):
#   docker run -d --name ccpanel -p 8888:8888 \
#     -e PANEL_PASSWORD='password-kuat' \
#     -e PANEL_JWT_SECRET=$(openssl rand -hex 32) \
#     -e CCPANEL_CERTBOT_EMAIL='admin@domainmu.com' \
#     -v ccpanel-data:/opt/ccpanel/data \
#     ccpanel

FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx mariadb-server php8.1-fpm php8.2-fpm php8.3-fpm \
        python3 python3-venv python3-pip openssl certbot python3-certbot-nginx \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ccpanel
COPY server.py requirements.txt ./
COPY core/ ./core/
COPY --from=frontend /build/static ./static

RUN python3 -m venv .venv \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

# volume untuk data SQLite + site + certbot + trash
VOLUME ["/opt/ccpanel/data", "/www/wwwroot", "/www/trash", "/etc/letsencrypt"]

# supervisord: nginx + mariadb + php-fpm + uvicorn
COPY docker/supervisord.conf /etc/supervisor/conf.d/ccpanel.conf
EXPOSE 8888 80 443
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/ccpanel.conf"]
