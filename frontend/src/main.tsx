import React from 'react';import ReactDOM from 'react-dom/client';import {BrowserRouter} from 'react-router-dom';import App from './App';import './styles.css';
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><App/></BrowserRouter></React.StrictMode>);
const connectivity=()=>document.documentElement.classList.toggle('offline',!navigator.onLine);window.addEventListener('online',connectivity);window.addEventListener('offline',connectivity);connectivity();
if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js'));
