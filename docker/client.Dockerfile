# --- Stage 1: Build Angular ---
FROM node:20-alpine AS build

WORKDIR /app
# Sadece bağımlılık dosyalarını kopyala ve yükle
COPY client/package*.json ./
RUN npm install

# Kalan client kaynak kodlarını kopyala
COPY client/ .

# Angular uygulamasını Production modunda derle
RUN npm run build --configuration=production

# --- Stage 2: Serve with Nginx ---
FROM nginx:alpine

# Nginx config dosyamızı içeri alıyoruz
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

# Derlenmiş dist dosyalarını Nginx'in sunacağı alana taşı
COPY --from=build /app/dist/client/browser /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
