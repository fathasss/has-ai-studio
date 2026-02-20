FROM nginx:alpine

# Copy static assets (to be generated)
# COPY ./web-cli/dist /usr/share/nginx/html

# For now, just allow it to serve the directory if we mount it
COPY ./docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
