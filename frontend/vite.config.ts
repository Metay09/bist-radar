import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({cacheDir:'.vite-cache',plugins:[react()],server:{proxy:{'/api':'http://localhost:8765'}},test:{environment:'jsdom',setupFiles:'./src/test-setup.ts',exclude:['e2e/**','node_modules/**']}});
