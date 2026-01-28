# AoE2 Replay Visualizer - Developer Guide

This document describes the architecture and implementation of the AoE2 Replay Visualizer.

## Project Overview

A browser-based tool to visualize Age of Empires II: Definitive Edition replay files (`.aoe2record`). Users can upload replay files, watch unit movements on an isometric map, and control playback.

## Architecture

```
visualizer/
├── server.py          # Flask backend - handles file uploads, match browsing, replay downloads
├── players.csv        # List of tracked players (name, profileId)
├── public/
│   ├── index.html     # Main HTML structure with match browser modals
│   ├── style.css      # Styling (full-screen map layout, modal panels)
│   └── app.js         # Main application controller with match browsing
├── renderer.js        # Canvas rendering (isometric projection)
├── playback.js        # Game state and animation engine
├── generate_data.py   # CLI tool to export replay to JSON
├── fetch_matches.py   # Prototype script for API testing
└── replay_data.json   # Pre-generated replay data (optional)
```

## Components

### Backend (server.py)

Flask server that:
- Serves static files (HTML, CSS, JS)
- Handles file uploads at `/api/upload` (POST)
- Processes `.aoe2record` files using mgz library
- Fetches match history from AoE2 Companion API
- Downloads and processes replays from aoe.ms
- Returns JSON data for the frontend

**Key endpoints:**
```
GET /api/matches
- Fetches recent Land Nomad matches from all players in players.csv
- Deduplicates matches, returns latest 25
- Returns: JSON array of match objects

GET /api/matches/<player_name>
- Fetches last 10 matches for a specific player
- Returns: JSON array of match objects

POST /api/load-match
- Accepts: JSON with match_id and profile_id
- Downloads replay ZIP from aoe.ms, extracts .aoe2record, parses with mgz
- Returns: JSON with match data, players, actions, units

POST /api/upload
- Accepts: multipart/form-data with 'file' field
- Returns: JSON with match data, players, actions, units
```

**External APIs:**
- AoE2 Companion API: `https://data.aoe2companion.com/api` (requires User-Agent header)
- Replay downloads: `https://aoe.ms/replay/?gameId={matchId}&profileId={profileId}`

**Running the server:**
```bash
cd visualizer
source ../venv/bin/activate
python3 server.py
# Opens at http://localhost:8000
```

### Frontend Components

#### app.js - Application Controller

Main orchestrator that:
- Initializes Renderer and Playback instances
- Handles file upload UI and match browsing
- Manages playback controls (play/pause, speed, timeline)
- Sets up keyboard shortcuts
- Manages player visibility toggles
- Fetches and displays match history from tracked players

**Key methods:**
- `init()` - Loads default replay or shows upload prompt
- `uploadReplay(file)` - Sends file to server, reinitializes on success
- `setupUI()` - Binds event listeners (only once via `controlsInitialized` flag)
- `togglePlay()` - Play/pause control
- `startRenderLoop()` - 60fps render loop using requestAnimationFrame
- `fetchMatches()` - Fetches Land Nomad matches from all tracked players
- `renderMatchList(matches)` - Displays match list in modal panel
- `renderMatchDetail(match)` - Shows match details with teams, civs, ratings
- `loadMatch(matchId, profileId)` - Downloads and loads a replay from aoe.ms

#### renderer.js - Canvas Rendering

Handles all drawing operations with isometric projection.

**Coordinate System:**
```javascript
// Game coords (0,0) to (mapSize, mapSize) -> Isometric canvas coords
gameToCanvas(gameX, gameY) {
    const isoX = (gameX + gameY) * (tileWidth / 2) * zoom;
    const isoY = (gameY - gameX) * (tileHeight / 2) * zoom;
    return { x: panX + isoX, y: panY + isoY };
}
```

**Diamond orientation:**
- (0, 0) = Left corner
- (maxX, 0) = Top corner
- (0, maxY) = Bottom corner
- (maxX, maxY) = Right corner

**Key features:**
- Auto-scales to fit container while maintaining aspect ratio
- Mouse wheel zoom (centered on cursor)
- Click-and-drag panning
- Different shapes for unit types (circles=villagers, triangles=military)
- Isometric diamonds for buildings

#### playback.js - Game State Engine

Manages game state over time with smooth interpolation.

**Key concepts:**
- Pre-processes all actions into movement timelines per unit
- Interpolates unit positions between commands for smooth movement
- Tracks unit spawns, deaths, and deletions
- Handles building construction timeline

**State structure:**
```javascript
{
    units: Map<name, {x, y, player, type, alive, dying}>,
    buildings: Map<key, {x, y, player, type}>,
    currentTime: float
}
```

**Death detection:**
- Military units idle for 5+ minutes before game end are marked as dead
- Death time = last_command_time + 5 minutes
- Dying units (within 30s of death) rendered at 50% opacity

### CSS Layout

Full-screen layout with:
- Header bar (title, match info, browse matches button)
- Map container (flex: 1, fills available space)
- Info panel (overlaid on map, top-left)
- Controls panel (fixed at bottom)
- Match list modal (overlay panel for browsing matches)
- Match detail modal (overlay panel for viewing match details before loading)

## Data Flow

### Direct Upload Flow
1. **Upload:** User selects `.aoe2record` file
2. **Process:** Flask saves to temp file, parses with mgz, extracts data
3. **Return:** JSON with match info, players, units, actions
4. **Initialize:** Frontend creates Renderer and Playback with data
5. **Render:** 60fps loop calls `playback.getState()` and `renderer.render(state)`
6. **Animate:** Playback advances time, interpolates unit positions

### Match Browser Flow
1. **Browse:** User clicks "Browse Matches" button
2. **Fetch:** Frontend calls `/api/matches` to get Land Nomad matches from tracked players
3. **Display:** Match list modal shows recent matches with map, date, players
4. **Select:** User clicks a match to see details (teams, civs, ratings, winner)
5. **Load:** User clicks "Load Replay" button
6. **Download:** Server fetches ZIP from aoe.ms, extracts .aoe2record, parses with mgz
7. **Initialize:** Same as direct upload flow from step 4

## Key Implementation Details

### Event Listener Management

To prevent duplicate listeners when uploading new replays:
```javascript
if (!this.controlsInitialized) {
    this.controlsInitialized = true;
    this.btnPlay.addEventListener("click", () => this.togglePlay());
    // ... other listeners
}
```

### Unit Position Interpolation

Units move smoothly between command positions:
```javascript
getUnitPosition(unit) {
    // Find prev and next movement commands around currentTime
    // Interpolate: pos = prev + (next - prev) * t
    const t = (currentTime - prevTime) / (nextTime - prevTime);
    return {
        x: prevX + (nextX - prevX) * t,
        y: prevY + (nextY - prevY) * t
    };
}
```

### Canvas Auto-Scaling

Map fits container while maintaining diamond aspect ratio:
```javascript
setupCanvas() {
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
    
    const scaleX = canvas.width / mapPixelWidth;
    const scaleY = canvas.height / mapPixelHeight;
    const fitScale = Math.min(scaleX, scaleY) * 0.9;
    
    if (zoom === 1) zoom = fitScale;
}
```

## Configuration

### players.csv

CSV file containing tracked players for match browsing:
```csv
name,profileId
ddk220,612690
Arkantos12,1314165
...
```

The server loads this file to fetch matches from all tracked players. Matches are:
- Fetched in batches from AoE2 Companion API
- Deduplicated by matchId
- Filtered to only include "Land Nomad" maps
- Sorted by date (newest first)
- Limited to 25 matches

## Dependencies

**Python:**
- Flask, flask-cors - Web server
- mgz - AoE2 replay parser
- aocref - Object name lookups
- requests - HTTP client for API calls

**Frontend:**
- Vanilla JavaScript (no frameworks)
- HTML5 Canvas for rendering

## Common Issues

1. **Port 5000 blocked:** macOS AirPlay uses port 5000. Use port 8000 instead.

2. **File upload fails:** Ensure Flask server is running, not simple HTTP server.

3. **Play button unresponsive:** Check browser console for errors. May be duplicate event listeners.

4. **Map squished:** Ensure `setupCanvas()` calculates proper fit scale.

5. **AoE2 Companion API 403 error:** Ensure User-Agent header is set in requests.

6. **Replay download fails:** Some replays may not be available on aoe.ms. Try a different match.

7. **Railway build cache:** If dependencies aren't updating, clear the build cache in Railway dashboard.

## Related Files

- `aoe2recordinsight.md` - Details on parsing `.aoe2record` files with mgz
- `README.md` - User-facing documentation
- `analyzers/` - Additional Python scripts for data extraction
