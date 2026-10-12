// Ajouter/fusionner ces options dans ton vite.config.ts existant.
// Elles sont nécessaires pour que le Hot Module Replacement (HMR)
// fonctionne correctement depuis l'intérieur d'un conteneur Docker.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  server: {
    host: '0.0.0.0',   // écoute sur toutes les interfaces (obligatoire en Docker)
    port: 5173,
    watch: {
      // Sur Linux (et Docker), utilise le polling si l'inotify ne se propage
      // pas correctement depuis l'hôte Windows/Mac vers le conteneur.
      usePolling: true,
      interval: 300,     // ms — augmenter si le CPU chauffe, baisser si trop lent
    },
    hmr: {
      // Le navigateur se connecte à localhost, pas au nom interne du conteneur
      host: 'localhost',
      port: 5173,
    },
  },
})