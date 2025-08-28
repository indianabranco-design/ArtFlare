# Deploy passo-a-passo (web + iPhone + Mac)

## A) Publicar na web (Streamlit Community Cloud)
1. Subir esta pasta (o teu projeto) para um repositório no GitHub.
2. Em https://share.streamlit.io → Deploy a public app from GitHub.
3. Repo: o teu repo; Branch: main; Main file path: `Home.py`.
4. (Opcional) Em Settings → Secrets, adiciona `APP_SHA256` se quiseres password.
5. Abre o URL que a plataforma gerar.

## B) App no iPhone (atalho ou nativa)
- Mais rápido: abrir o URL no Safari → Partilhar → **Adicionar ao Ecrã Principal**.
- Nativa: usa a pasta `ios_wrapper_swiftui/` (Xcode, WKWebView) e define a tua URL em `AppConstants.swift`.

## C) App no Mac (desktop)
- Usa a pasta `electron_wrapper/`:
  - `npm install`
  - Edita `main.js` e muda `APP_URL` para o teu URL
  - `npm start` (teste) / `npm run build` (gera .app)

## D) Secrets (exemplo)
Cria `.streamlit/secrets.toml` a partir do `secrets.toml.example`.

## E) Notas
- SQLite na nuvem é temporário: para produção, usa Postgres (Neon/Supabase).
- Atualizações: faz `git push` e a app é re-publicada automaticamente.
