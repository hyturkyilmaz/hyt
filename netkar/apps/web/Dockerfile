# syntax=docker/dockerfile:1
# NetTablo web (Next.js) imajı. Çok aşamalı, standalone çıktı, root olmayan kullanıcı.

# Node sürümü package.json engines (>=22) ve CI (node 22) ile uyumlu, tam sürüm etiketiyle sabit.
# Özet (digest) sabitleme dağıtım hattında yapılır (docs/operasyon/staging_ve_dagitim_plani.md).
ARG NODE_VERSION=22.23.4

# ---- Bağımlılıklar: yalnız manifest dosyaları (katman önbelleği) --------------------
FROM node:${NODE_VERSION}-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- Derleme: .next/standalone üretir -------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# /api/v1 rewrite hedefi DERLEME anında .next/routes-manifest.json içine gömülür; çalışma anındaki
# API_BASE_URL rewrite'ı değiştirmez. Bu yüzden değer burada verilmelidir (compose: build.args).
ARG API_BASE_URL=http://api:8000
ENV API_BASE_URL=${API_BASE_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# public/ boş olabilir ve git boş dizini izlemez; çalışma aşamasındaki COPY kırılmasın diye garanti edilir.
RUN mkdir -p public && npm run build

# ---- Çalışma: yalnız standalone çıktı, derleyici ve devDependencies yok ------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN groupadd --system --gid 10001 nettablo \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin nettablo
COPY --from=build --chown=10001:10001 /app/public ./public
COPY --from=build --chown=10001:10001 /app/.next/standalone ./
COPY --from=build --chown=10001:10001 /app/.next/static ./.next/static
USER 10001:10001
EXPOSE 3000
# HEALTHCHECK bilerek yok: web uygulamasında sağlık yolu (health route) bulunmuyor. Sağlık yolu eklenince
# bu satırın yerine node ile o yola istek atan bir HEALTHCHECK konmalıdır.
CMD ["node", "server.js"]
