# Alberto web console (Next.js 14, standalone output). BUILD CONTEXT = repo root
FROM node:22-alpine AS deps
WORKDIR /repo
RUN corepack enable
# Lockfile + workspace manifests first for cached installs.
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile || pnpm install

FROM node:22-alpine AS builder
WORKDIR /repo
RUN corepack enable
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/frontend/node_modules ./frontend/node_modules
COPY . .
# Server-side rewrite target, baked at build time (standalone freezes rewrite destinations).
# Default keeps plain `docker build` / host behavior; compose overrides it to http://api:8000.
# NOT exported as NEXT_PUBLIC_* so it never leaks into the browser bundle (see next.config.mjs).
ARG FORGE_API_URL=http://127.0.0.1:8000
ENV FORGE_API_URL=${FORGE_API_URL}
# Clear any stale incremental cache (see memory: stale .next can break the build).
# NEXT_OUTPUT=standalone emits the self-contained server bundle (symlinks work on Linux).
ENV NEXT_OUTPUT=standalone
RUN rm -rf frontend/.next && pnpm --filter alberto-frontend build || pnpm --filter web build

FROM node:22-alpine AS runner
WORKDIR /repo
ENV NODE_ENV=production
RUN addgroup -g 10002 nodejs && adduser -u 10002 -G nodejs -S nextjs
# Standalone bundle preserves the workspace layout (frontend/server.js).
COPY --from=builder /repo/frontend/.next/standalone ./
COPY --from=builder /repo/frontend/.next/static ./frontend/.next/static
COPY --from=builder /repo/frontend/public ./frontend/public
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "frontend/server.js"]
