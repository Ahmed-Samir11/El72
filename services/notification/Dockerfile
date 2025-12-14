FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --silent || npm install
COPY . .
CMD ["node", "dist/index.js"]
