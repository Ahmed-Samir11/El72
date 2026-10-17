# Multi-stage build for the El72 landing page.
# Stage 1: build the Vite site.
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: serve the static site with nginx.
FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/html
