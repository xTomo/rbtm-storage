# Базовый образ закреплён вместе с выпуском Debian. Голый тег python:3.11-slim переезжает на каждый новый Debian
# (в 2026 году он уже на trixie) и обновляется вместе с ним — после каждого такого переезда кэш слоёв не годится
# и образ собирается с нуля (apt, pip). Обновлять базу — сознательно, сменой тега здесь.
FROM python:3.11-slim-bookworm

MAINTAINER buzmakov

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Без RUN --mount (кэш BuildKit): на сервере docker-compose v1 собирает классическим сборщиком, он этот флаг
# не знает. Слои apt и pip берутся из кэша слоёв, пока не меняются база, список пакетов или requirements_docker.txt.
RUN apt-get update \
 && apt-get install -y nginx supervisor pkg-config \
                       libfreetype6-dev \
 && rm -rf /var/lib/apt/lists/*

# Зависимости — до копирования кода: правка кода не трогает слои apt и pip.
COPY requirements_docker.txt /var/www/storage/requirements_docker.txt
WORKDIR /var/www/storage/

RUN pip install --no-cache-dir -r requirements_docker.txt

COPY . /var/www/storage/

# RUN echo "MONGODB_URI = 'mongodb://database:27017'" > conf.py
ENV YOURAPPLICATION_SETTINGS=conf.py

# setup nginx
RUN mkdir -p logs && echo "daemon off;" >> /etc/nginx/nginx.conf \
    && rm /etc/nginx/sites-enabled/default \
    && cp /var/www/storage/storage_nginx.conf /etc/nginx/sites-available/ \
    && ln -s /etc/nginx/sites-available/storage_nginx.conf /etc/nginx/sites-enabled/

# setup supervisord
# RUN mkdir -p /var/log/supervisor
RUN cp storage_supervisord.conf /etc/supervisor/conf.d/

EXPOSE 5006
CMD ["supervisord", "-n"]
