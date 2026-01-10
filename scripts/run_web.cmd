@echo off
setlocal
cd /d %~dp0\..\apps\web-shell
npm install
npm run dev
