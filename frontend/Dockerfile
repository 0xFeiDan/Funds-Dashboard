FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install
FROM deps AS build
COPY . .
RUN npm run build
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
USER app
EXPOSE 3000
CMD ["npm","start"]
