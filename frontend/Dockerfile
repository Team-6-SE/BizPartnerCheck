
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# The sign-in server is built into the app (Vite reads VITE_* at build time).
ARG VITE_OIDC_AUTHORITY
ENV VITE_OIDC_AUTHORITY=$VITE_OIDC_AUTHORITY
RUN npm run build

FROM nginx:1.27-alpine

# Single-page app: every path (e.g. /partners, /auth/callback) gets index.html.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
