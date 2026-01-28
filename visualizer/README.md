# AoE2 Replay Visualizer

A web-based visualizer for Age of Empires II: Definitive Edition replay files.

## Features

- Upload and parse `.aoe2record` replay files
- Isometric map view with unit and building sprites
- Playback controls with variable speed (1x, 2x, 4x, 8x, 12x, 16x)
- Player visibility toggles
- Action log with timestamped events
- Wall rendering
- Speed-based unit movement interpolation

## Local Development

```bash
cd visualizer
pip install flask flask-cors mgz
python server.py
```

Open http://localhost:8000

## Deploy to Railway

### Steps

1. **Create a Railway account** at https://railway.app

2. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

3. **Deploy via GitHub** (easiest):
   - Push your code to GitHub
   - Go to https://railway.app/new
   - Click "Deploy from GitHub repo"
   - Select your repository
   - Railway will auto-detect Python and deploy

4. **Or deploy via CLI**:
   ```bash
   cd visualizer
   railway init
   railway up
   ```

5. Your app will be available at the URL Railway provides (e.g., `https://your-app.up.railway.app`)

### Environment Variables

Railway automatically sets the `PORT` environment variable. No additional configuration needed.

## Project Structure

```
visualizer/
├── server.py          # Flask server (Railway & local)
├── requirements.txt   # Python dependencies
├── Procfile           # Railway process file
├── railway.json       # Railway configuration
├── public/            # Static assets
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   ├── renderer.js
│   └── playback.js
└── generate_data.py   # Standalone replay parser
```

## Troubleshooting

### CORS errors
The server includes CORS headers. If you're still having issues, check browser console for specific errors.

### Large replay files
Very large replays may take longer to process. The server has no file size limit.
