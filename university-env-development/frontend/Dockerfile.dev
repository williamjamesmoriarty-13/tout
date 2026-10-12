# Dockerfile.dev — React/Vite
# Mettre ce fichier dans : frontend/Dockerfile.dev
#
# Node tourne dans le conteneur — tu n'as pas besoin de l'installer sur ton PC.
# Le dossier frontend/ est monté en volume → HMR fonctionne immédiatement.

FROM node:20-alpine

WORKDIR /app

# Copie package.json pour installer les dépendances au build de l'image.
# node_modules reste dans le conteneur (volume anonyme dans compose),
# donc jamais sur ton PC (évite les conflits Linux/Windows).
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# Le code source arrive via le volume monté par docker-compose.dev.yml.
# Pas de COPY . . ici.

EXPOSE 3000

# --host 0.0.0.0 obligatoire pour que le port soit accessible depuis l'hôte
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
