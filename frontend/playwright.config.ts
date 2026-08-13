import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',outputDir:'/tmp/bist-radar-playwright-results',webServer:{command:'npm run dev -- --host 127.0.0.1',url:'http://127.0.0.1:5173',reuseExistingServer:true},use:{baseURL:'http://127.0.0.1:5173'}});
