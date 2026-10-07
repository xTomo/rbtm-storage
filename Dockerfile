# Базовый образ закреплён вместе с выпуском Debian. Голый тег python:3.11-slim переезжает на каждый новый Debian
# (в 2026 году он уже на trixie) и обновляется вместе с ним — после каждого такого переезда кэш слоёв не годится
# и образ собирается с нуля (apt, pip). Обновлять базу — сознательно, сменой тега здесь.
FROM python:3.11-slim-bookworm

MAINTAINER buzmakov

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Кэш apt и pip — в кэш-монтированиях BuildKit (docker compose v2 собирает через BuildKit): даже если слой
# пересобирается, пакеты не скачиваются заново. В сам образ кэш не попадает.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
 && apt-get update \
 && apt-get install -y nginx supervisor pkg-config \
                       libfreetype6-dev

# Зависимости — до копирования кода: правка кода не трогает слои apt и pip.
COPY requirements_docker.txt /var/www/storage/requirements_docker.txt
WORKDIR /var/www/storage/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements_docker.txt

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
