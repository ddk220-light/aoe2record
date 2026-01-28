# AoE2 Replay Analyzer & Visualizer

A collection of Python tools to analyze Age of Empires II: Definitive Edition replay files (`.aoe2record`) and a browser-based visualizer to watch the game unfold.

## Features

- **Extract game statistics** to CSV files (units, buildings, technologies, actions)
- **Track unit journeys** with full action history for each unit
- **Detect unit deaths** based on inactivity threshold
- **Browser-based visualizer** with isometric diamond map view
- **Playback controls** with variable speed and timeline scrubbing

## Project Structure

```
aoe2record/
├── analyzers/           # Python analysis scripts
│   ├── extract_stats.py      # Export all stats to CSV files
│   ├── extract_journeys.py   # Track unit journeys
│   ├── aoe2_analyzer.py      # Basic replay analysis
│   ├── unit_analyzer.py      # Detailed unit analysis
│   ├── unit_journey.py       # Villager journey tracking
│   └── military_journey.py   # Military unit tracking with death detection
├── visualizer/          # Browser-based replay visualizer
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   ├── renderer.js
│   ├── playback.js
│   └── generate_data.py      # Export replay to JSON for visualizer
├── docs/                # Documentation
├── replays/             # Place replay files here
└── download_replays.py  # Download replays from aoe2.net
```

## Installation

### Prerequisites

- Python 3.8+
- pip

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/aoe2record.git
   cd aoe2record
   ```

2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install mgz aocref
   ```

## Usage

### Extract Statistics to CSV

```bash
python analyzers/extract_stats.py your_replay.aoe2record
```

This creates a folder with 10 CSV files:
- `match_info.csv` - General match information
- `players.csv` - Player details
- `units.csv` - All units trained
- `buildings.csv` - All buildings constructed
- `technologies.csv` - All technologies researched
- `actions_summary.csv` - Actions per minute per player
- `unit_summary.csv` - Summary stats per unit
- `all_actions.csv` - Every action with full details
- `actions_readable.csv` - Human-readable action log with named units
- `player_totals.csv` - Aggregate stats per player

### Extract Unit Journeys

```bash
python analyzers/extract_journeys.py your_replay.aoe2record
```

Creates a CSV with one row per unit showing their complete action history.

### Use the Visualizer

1. Generate the JSON data:
   ```bash
   cd visualizer
   python generate_data.py
   ```

2. Start a local server:
   ```bash
   python -m http.server 8000
   ```

3. Open http://localhost:8000 in your browser

### Visualizer Controls

- **Space**: Play/Pause
- **Arrow keys**: Step forward/backward
- **1/2/4/8**: Set playback speed
- **Mouse wheel**: Zoom in/out
- **Click + drag**: Pan the map
- **Player checkboxes**: Toggle player visibility

## Map Orientation

The visualizer uses AoE2's isometric diamond view:
- **(0, 0)** is at the **left** corner
- **(max, 0)** is at the **top** corner  
- **(0, max)** is at the **bottom** corner
- **(max, max)** is at the **right** corner

## Dependencies

- [mgz](https://github.com/happyleavesaoc/aoc-mgz) - AoE2 recorded game parser
- [aocref](https://github.com/happyleavesaoc/aoc-mgz) - AoE2 reference data (unit names, etc.)

## License

MIT License
