FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache python3 py3-pip tesseract-ocr \
    && python3 -m venv /opt/venv
COPY server/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
COPY server /app/server
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entry.sh /docker-entry.sh
RUN chmod +x /docker-entry.sh
COPY --from=build /app/dist /usr/share/nginx/html
ENV GALLEY_DATA=/data
VOLUME /data
CMD ["/docker-entry.sh"]
