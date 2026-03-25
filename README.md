# textanalysis

A Flask web application that analyzes texting conversations (and other text-dense screenshots) using chess-style move evaluations.

## Installation

```bash
git clone https://github.com/ang-or-five/textanalysis.git
cd textanalysis
pip install -r requirements.txt
```

### UV users:
```bash
git clone https://github.com/ang-or-five/textanalysis.git
cd textanalysis
uv pip install -r requirements.txt --system
```

## Configuration

1. Copy `.env.example` to `.env`
2. Get a free API key from https://aistudio.google.com/api-keys
3. Paste your API key in `.env`

## Usage

```bash
python app.py
```

Open http://localhost:5000 in your browser.

1. Drag and drop or click to upload one or more conversation screenshots
2. Select analysis options:
   - **Concatenate** - Treat multiple images as one continuous thread
   - **OCR Only** - Skip image analysis (faster)
   - **Dense Analysis** - Analyze every line in detail
3. Click "Analyze"
4. Browse results using the different view tabs



## Demo

Upload a screenshot of a conversation and watch as each message gets evaluated with chess-style ratings:
- **Brilliant** - Exceptionally clever or witty
- **Great Find** - Great observation or comeback
- **Best** - The optimal response
- **Excellent** - Very well crafted
- **Good** - Solid, appropriate
- **Book** - Standard/expected
- **Inaccuracy** - Slightly off
- **Mistake** - Poor choice or timing
- **Blunder** - Major error or cringe
- **Missed Win** - Missed opportunity

## Features

- **Multiple View Modes**
  - **Append Replay** - Watch messages appear one-by-one with animated evaluations
  - **Semi-Annotated** - Original image with evaluation icons overlaid
  - **Full Annotated** - Each message shown with evaluation and explanation
  - **Interactive** - Click through messages at your own pace

- **Multi-Image Support**
  - Upload multiple images at once
  - **Concatenate mode** - Combine multiple screenshots into one continuous analysis
  - Navigate between different analyzed images

- **Analysis Options**
  - **Dense Mode** - Analyze every single line/message exhaustively
  - **OCR Only** - Faster analysis without sending images to the model

- **Notable Icons** - Additional tags like "Winner", "Threat", "Sharp", "Forced", etc.

## Tech Stack

- **Backend**: Flask (Python)
- **OCR**: EasyOCR
- **LLM**: OpenAI-compatible API (tested with Gemini)
- **Image Processing**: Pillow, cairosvg


## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/api/upload` | POST | Upload image file |
| `/api/analyze` | POST | Analyze single image |
| `/api/analyze-multiple` | POST | Analyze multiple images separately |
| `/api/analyze-concatenated` | POST | Analyze multiple images as one |

## Project Structure

```
./
├── app.py                 # Flask application
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (not tracked)
├── .env.example           # Example environment variables
├── static/
│   ├── js/
│   │   └── script.js      # Frontend JavaScript
│   ├── images/            # Evaluation icons (SVG)
│   ├── uploads/           # Uploaded images (generated)
│   └── analysis/          # Analysis outputs (generated)
└── templates/
    └── index.html         # Web interface
```

## Extending the Analysis

The system prompt and evaluation schema can be customized in `app.py`:

- `EVALUATION_ICONS` - Available evaluation ratings
- `NOTABLE_ICONS` - Available notable tags
- `SYSTEM_PROMPT` - Instructions for the LLM

## Credits

Evaluation icons are ripped from chess.com's analysis interface
