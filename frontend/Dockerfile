FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=http://127.0.0.1:8000
ARG VITE_ENABLE_STAGE2=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_ENABLE_STAGE2=${VITE_ENABLE_STAGE2}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD wget -q -O /dev/null http://127.0.0.1/
