# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
# The UI always calls its own origin (/api is proxied by nginx). The page's
# Content-Security-Policy (connect-src 'self') relies on that.
ENV VITE_API_URL=""
# Optional organisation name for the title bar (e.g. ORG_NAME=Soilens in .env).
ARG VITE_ORG_NAME=""
ENV VITE_ORG_NAME=${VITE_ORG_NAME}
RUN npm run build

FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
