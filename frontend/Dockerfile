FROM node:18-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Production build: no dev overlay, no hot-reload socket, no development-only
# console messages (subject V.1: no errors, warnings or notices in the console).
RUN npm run build
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "run", "start"]
