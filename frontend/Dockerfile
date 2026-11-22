# Stage 1: Build SvelteKit static SPA using Bun
FROM oven/bun:1-alpine AS builder

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

ARG PUBLIC_API_BASE_URL=""
ARG PUBLIC_GOOGLE_CLIENT_ID=""
ARG PUBLIC_SCORE_SCALE=100

ENV PUBLIC_API_BASE_URL=$PUBLIC_API_BASE_URL \
    PUBLIC_GOOGLE_CLIENT_ID=$PUBLIC_GOOGLE_CLIENT_ID \
    PUBLIC_SCORE_SCALE=$PUBLIC_SCORE_SCALE

RUN bun run build

# Stage 2: Serve static build with Nginx
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/build /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
