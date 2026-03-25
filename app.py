from flask import Flask, render_template, request, jsonify
from py_toon_format import encode
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import cairosvg
import os
import json
import easyocr
import uuid
import io
import base64

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ANALYSIS_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'analysis')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ANALYSIS_FOLDER, exist_ok=True)

client = OpenAI(
    api_key=os.getenv('API_KEY'),
    base_url=os.getenv('BASE_URL')
)

DEFAULT_MODEL = os.getenv('MODEL', 'gemini-3-flash-preview')

reader = easyocr.Reader(['en'], gpu=True)

EVALUATION_ICONS = [
    'brilliant', 'great_find', 'best', 'excellent', 'good', 'book',
    'inaccuracy', 'mistake', 'blunder', 'missed_win'
]

NOTABLE_ICONS = [
    'winner', 'threat', 'take_back', 'sharp', 'mate', 'forced',
    'free_piece', 'fast_win', 'critical', 'alternative'
]

EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "box_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "IDs of text boxes that form this message"
                    },
                    "evaluation": {
                        "type": "string",
                        "enum": EVALUATION_ICONS,
                        "description": "The evaluation icon to display"
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of the evaluation"
                    },
                    "notable": {
                        "type": "array",
                        "items": {"type": "string", "enum": NOTABLE_ICONS},
                        "description": "Optional notable icons (used often but not always)"
                    }
                },
                "required": ["box_ids", "evaluation", "explanation"]
            }
        },
        "skipped_boxes": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Box IDs that were skipped (UI text, timestamps, etc.)"
        }
    },
    "required": ["groups", "skipped_boxes"]
}

SYSTEM_PROMPT = """You are a text analyst that evaluates content using chess-style analysis. You receive OCR data from a screenshot.

While primarily designed for texting conversations, you can analyze ANY text-dense screenshot: lyrics, social media posts, articles, emails, comments, chat logs, memes with text, etc. Adapt your analysis to the content type.

Your job is to:
1. Group text boxes that belong to the same logical unit (message, line, paragraph, etc.)
2. Evaluate each unit using chess-style evaluations
3. Skip boxes that are UI elements (timestamps, "Read", "Delivered", app names, etc.)

Evaluation options (use these for the 'evaluation' field):
- brilliant: Exceptionally clever, witty, or impressive content
- great_find: Great observation, insight, or comeback
- best: The optimal content in the situation
- excellent: Very well crafted
- good: Solid, appropriate
- book: Standard/expected (nothing special)
- inaccuracy: Slightly off or could be better
- mistake: Poor choice or timing
- blunder: Major error, cringe, or bad take
- missed_win: Missed opportunity for something great

Notable options (optional, use when relevant):
- winner: Clear winner
- threat: Warning sign or red flag
- take_back: Should be deleted/unsent
- sharp: Clever or cutting
- mate: Game over, definitive end
- forced: Awkward or unnatural
- free_piece: Easy opportunity taken
- fast_win: Quick victory
- critical: Critical moment
- alternative: Could have been different

Provide brief, punchy explanations. Be humorous when appropriate. Adapt your analysis style to the content type (e.g., rate lyrics on cleverness/flow, social media on engagement/impact)."""

DENSE_PROMPT = """

IMPORTANT - DENSE ANALYSIS MODE: You must analyze EVERY single text unit exhaustively. Do not skip or group items unless they are purely UI elements. Even short or mundane messages must receive an evaluation. Be thorough and leave no text unanalyzed."""


def get_system_prompt(dense_mode=False):
    if dense_mode:
        return SYSTEM_PROMPT + DENSE_PROMPT
    return SYSTEM_PROMPT


def render_svg_to_png(svg_path, size):
    png_data = cairosvg.svg2png(url=svg_path, output_width=size, output_height=size)
    if png_data is None:
        return Image.new('RGBA', (size, size), (0, 0, 0, 0))
    return Image.open(io.BytesIO(png_data)).convert('RGBA')


def get_group_bounds(group, text_lines):
    y_mins = []
    y_maxs = []
    x_mins = []
    x_maxs = []
    for box_id in group['box_ids']:
        line = next((l for l in text_lines if l['id'] == box_id), None)
        if line:
            y_mins.append(line['bbox_normalized']['y_min'])
            y_maxs.append(line['bbox_normalized']['y_max'])
            x_mins.append(line['bbox_normalized']['x_min'])
            x_maxs.append(line['bbox_normalized']['x_max'])
    return (min(y_mins) if y_mins else 0, max(y_maxs) if y_maxs else 0,
            min(x_mins) if x_mins else 0, max(x_maxs) if x_maxs else 0)


def calculate_slice_boundaries(groups, text_lines, img_height):
    if not groups:
        return []
    
    boundaries = []
    for i, group in enumerate(groups):
        y_min, y_max, x_min, x_max = get_group_bounds(group, text_lines)
        
        if i == 0:
            slice_start = 0
        else:
            prev_y_min, prev_y_max, _, _ = get_group_bounds(groups[i-1], text_lines)
            slice_start = int((prev_y_max + y_min) / 2)
        
        if i == len(groups) - 1:
            slice_end = img_height
        else:
            next_y_min, _, _, _ = get_group_bounds(groups[i+1], text_lines)
            slice_end = int((y_max + next_y_min) / 2)
        
        boundaries.append({
            'group_idx': i,
            'y_start': slice_start,
            'y_end': slice_end,
            'x_max': int(x_max),
            'group': group
        })
    
    return boundaries


def create_annotated_slice(img_slice, group, analysis_id, slice_idx):
    icon_size = 32
    padding = 8
    
    width, height = img_slice.size
    new_width = width + 60
    
    new_img = Image.new('RGBA', (new_width, height), (255, 255, 255, 255))
    new_img.paste(img_slice, (0, 0))
    
    eval_icon_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{group['evaluation']}.svg")
    if os.path.exists(eval_icon_path):
        icon = render_svg_to_png(eval_icon_path, icon_size)
        new_img.paste(icon, (width + padding, padding), icon)
    
    if group.get('notable'):
        notable_y = padding + icon_size + 4
        for notable in group['notable'][:2]:
            notable_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{notable}.svg")
            if os.path.exists(notable_path):
                icon = render_svg_to_png(notable_path, 24)
                new_img.paste(icon, (width + padding, notable_y), icon)
                notable_y += 28
    
    slice_filename = f"{analysis_id}_slice_{slice_idx}.png"
    slice_path = os.path.join(ANALYSIS_FOLDER, slice_filename)
    new_img.save(slice_path)
    
    return f"/static/analysis/{slice_filename}"


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = font.getbbox(test_line)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def create_full_annotated_image(img, boundaries, analysis_id):
    annotated_slices = []
    max_width = 0
    total_height = 0
    
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small_font = ImageFont.truetype("arial.ttf", 12)
    except:
        font = ImageFont.load_default()
        small_font = font
    
    for boundary in boundaries:
        y_start = int(max(0, boundary['y_start']))
        y_end = int(min(img.height, boundary['y_end']))
        
        if y_end <= y_start:
            continue
        
        img_slice = img.crop((0, y_start, img.width, y_end))
        
        icon_size = 32
        padding = 8
        text_width = 280
        new_width = img.width + text_width
        
        explanation = boundary['group'].get('explanation', '')
        notable = boundary['group'].get('notable', [])
        
        eval_name = boundary['group']['evaluation'].replace('_', ' ').title()
        wrapped_explanation = wrap_text(explanation, small_font, text_width - padding * 2)
        
        total_text_lines = 1 + len(wrapped_explanation)
        text_height = total_text_lines * 18 + 30
        if notable:
            text_height += 30
        
        slice_height = max(img_slice.height, text_height)
        
        new_img = Image.new('RGBA', (new_width, slice_height), (255, 255, 255, 255))
        new_img.paste(img_slice, (0, 0))
        
        text_x = img.width + padding
        text_y = padding
        
        draw = ImageDraw.Draw(new_img)
        eval_icon_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{boundary['group']['evaluation']}.svg")
        if os.path.exists(eval_icon_path):
            icon = render_svg_to_png(eval_icon_path, 24)
            new_img.paste(icon, (int(text_x), int(text_y)), icon)
            text_x += 30
        
        eval_color = {
            'brilliant': '#1abc9c', 'great_find': '#1abc9c', 'best': '#1abc9c',
            'excellent': '#27ae60', 'good': '#3498db', 'book': '#7f8c8d',
            'inaccuracy': '#f39c12', 'mistake': '#e67e22', 'blunder': '#e74c3c',
            'missed_win': '#9b59b6'
        }.get(boundary['group']['evaluation'], '#7f8c8d')
        
        draw.text((text_x, text_y + 3), eval_name, fill=eval_color, font=font)
        text_y += 24
        
        for line in wrapped_explanation:
            draw.text((img.width + padding, text_y), line, fill='#333333', font=small_font)
            text_y += 16
        
        text_y += 8
        
        if notable:
            notable_x = img.width + padding
            for n in notable[:3]:
                notable_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{n}.svg")
                if os.path.exists(notable_path):
                    icon = render_svg_to_png(notable_path, 20)
                    new_img.paste(icon, (int(notable_x), int(text_y)), icon)
                    notable_x += 26
        
        annotated_slices.append(new_img)
        max_width = max(max_width, new_width)
        total_height += slice_height
    
    if not annotated_slices:
        return None
    
    full_annotated = Image.new('RGBA', (int(max_width), int(total_height)), (255, 255, 255, 255))
    y_offset = 0
    for slice_img in annotated_slices:
        full_annotated.paste(slice_img, (0, int(y_offset)))
        y_offset += slice_img.height
    
    full_annotated_filename = f"{analysis_id}_full_annotated.png"
    full_annotated_path = os.path.join(ANALYSIS_FOLDER, full_annotated_filename)
    full_annotated.save(full_annotated_path)
    
    return f"/static/analysis/{full_annotated_filename}"


def create_semi_annotated_image(img, boundaries, analysis_id):
    semi_img = img.copy()
    icon_size = 48
    padding = 16
    
    for boundary in boundaries:
        y_start = int(max(0, boundary['y_start']))
        y_end = int(min(img.height, boundary['y_end']))
        x_max = int(boundary.get('x_max', img.width))
        
        if y_end <= y_start:
            continue
        
        center_y = (y_start + y_end) // 2
        
        icon_right_edge = min(x_max + icon_size + padding, img.width - padding)
        x_pos = int(icon_right_edge - icon_size)
        y_pos = int(center_y - icon_size // 2)
        
        eval_icon_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{boundary['group']['evaluation']}.svg")
        if os.path.exists(eval_icon_path):
            icon = render_svg_to_png(eval_icon_path, icon_size)
            semi_img.paste(icon, (x_pos, y_pos), icon)
    
    semi_filename = f"{analysis_id}_semi.png"
    semi_path = os.path.join(ANALYSIS_FOLDER, semi_filename)
    semi_img.save(semi_path)
    
    return f"/static/analysis/{semi_filename}"


def create_append_slices(img, boundaries, analysis_id):
    icon_size = 48
    padding = 12
    extra_width = 80
    
    append_slices = []
    
    slice_heights = []
    for boundary in boundaries:
        y_start = int(max(0, boundary['y_start']))
        y_end = int(min(img.height, boundary['y_end']))
        x_max = int(boundary.get('x_max', img.width))
        if y_end > y_start:
            slice_heights.append((y_start, y_end, x_max, boundary))
    
    if not slice_heights:
        return []
    
    for i in range(len(slice_heights)):
        total_height = 0
        for j in range(i + 1):
            y_start, y_end, _, _ = slice_heights[j]
            total_height += (y_end - y_start)
        
        append_img = Image.new('RGBA', (img.width + extra_width, total_height), (255, 255, 255, 255))
        
        y_offset = 0
        for j in range(i + 1):
            y_start, y_end, x_max, boundary = slice_heights[j]
            img_slice = img.crop((0, y_start, img.width, y_end))
            
            slice_with_icon = Image.new('RGBA', (img.width + extra_width, img_slice.height), (255, 255, 255, 255))
            slice_with_icon.paste(img_slice, (0, 0))
            
            center_y = img_slice.height // 2
            
            x_pos = img.width + padding
            y_pos = center_y - icon_size // 2
            
            eval_icon_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{boundary['group']['evaluation']}.svg")
            if os.path.exists(eval_icon_path):
                icon = render_svg_to_png(eval_icon_path, icon_size)
                slice_with_icon.paste(icon, (int(x_pos), int(y_pos)), icon)
            
            notable_x = x_pos + icon_size + 4
            notable_y = y_pos
            if boundary['group'].get('notable'):
                for notable in boundary['group']['notable'][:2]:
                    notable_path = os.path.join(os.path.dirname(__file__), 'static', 'images', f"{notable}.svg")
                    if os.path.exists(notable_path):
                        icon = render_svg_to_png(notable_path, 32)
                        slice_with_icon.paste(icon, (int(notable_x), int(notable_y)), icon)
                        notable_y += 36
            
            append_img.paste(slice_with_icon, (0, int(y_offset)))
            y_offset += img_slice.height
        
        append_filename = f"{analysis_id}_append_{i}.png"
        append_path = os.path.join(ANALYSIS_FOLDER, append_filename)
        append_img.save(append_path)
        
        append_slices.append({
            'idx': i,
            'url': f"/static/analysis/{append_filename}"
        })
    
    return append_slices


def process_image(filepath, groups, text_lines):
    img = Image.open(filepath).convert('RGBA')
    img_width, img_height = img.size
    
    analysis_id = str(uuid.uuid4())[:8]
    
    full_filename = f"{analysis_id}_full.png"
    full_path = os.path.join(ANALYSIS_FOLDER, full_filename)
    img.save(full_path)
    
    boundaries = calculate_slice_boundaries(groups, text_lines, img_height)
    
    slices = []
    for boundary in boundaries:
        slice_idx = boundary['group_idx']
        y_start = max(0, boundary['y_start'])
        y_end = min(img_height, boundary['y_end'])
        
        if y_end <= y_start:
            continue
        
        img_slice = img.crop((0, y_start, img_width, y_end))
        
        slice_url = create_annotated_slice(img_slice, boundary['group'], analysis_id, slice_idx)
        
        slices.append({
            'idx': slice_idx,
            'url': slice_url,
            'y_start': y_start,
            'y_end': y_end,
            'evaluation': boundary['group']['evaluation'],
            'explanation': boundary['group']['explanation'],
            'notable': boundary['group'].get('notable', []),
            'box_ids': boundary['group']['box_ids']
        })
    
    full_annotated_url = create_full_annotated_image(img, boundaries, analysis_id)
    append_slices = create_append_slices(img, boundaries, analysis_id)
    semi_annotated_url = create_semi_annotated_image(img, boundaries, analysis_id)
    
    return {
        'analysis_id': analysis_id,
        'full_image': f"/static/analysis/{full_filename}",
        'full_annotated': full_annotated_url,
        'semi_annotated': semi_annotated_url,
        'slices': slices,
        'append_slices': append_slices
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    
    return jsonify({'filename': file.filename, 'filepath': filepath})


@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    filepath = data.get('filepath', '')
    no_image = data.get('no_image', False)
    dense_mode = data.get('dense_mode', False)
    
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 400
    
    results = reader.readtext(filepath)
    
    text_lines = []
    for idx, (bbox, text, confidence) in enumerate(results):
        x_coords = [float(p[0]) for p in bbox]
        y_coords = [float(p[1]) for p in bbox]
        text_lines.append({
            'id': int(idx),
            'text': text,
            'confidence': round(float(confidence), 3),
            'bbox': [[float(p[0]), float(p[1])] for p in bbox],
            'bbox_normalized': {
                'x_min': min(x_coords),
                'x_max': max(x_coords),
                'y_min': min(y_coords),
                'y_max': max(y_coords)
            }
        })
    
    text_lines.sort(key=lambda x: x['bbox_normalized']['y_min'])
    
    for i, line in enumerate(text_lines):
        line['id'] = i
    
    toon_data = encode({'lines': text_lines})
    
    system_prompt = get_system_prompt(dense_mode)
    
    if no_image:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Analyze this texting conversation (OCR data only):\n\n{toon_data}"}
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'text_evaluation',
                    'schema': EVALUATION_SCHEMA
                }
            }
        )
    else:
        with open(filepath, 'rb') as img_file:
            img_base64 = base64.standard_b64encode(img_file.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/png;base64,{img_base64}'
                            }
                        },
                        {
                            'type': 'text',
                            'text': f"Analyze this texting conversation:\n\n{toon_data}"
                        }
                    ]
                }
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'text_evaluation',
                    'schema': EVALUATION_SCHEMA
                }
            }
        )
    
    content = response.choices[0].message.content or '{}'
    llm_result = json.loads(content)
    
    image_data = process_image(filepath, llm_result.get('groups', []), text_lines)
    
    return jsonify({
        'analysis_id': image_data['analysis_id'],
        'full_image': image_data['full_image'],
        'full_annotated': image_data['full_annotated'],
        'semi_annotated': image_data['semi_annotated'],
        'slices': image_data['slices'],
        'append_slices': image_data['append_slices'],
        'text_lines': text_lines,
        'analysis': llm_result
    })


@app.route('/api/analyze-multiple', methods=['POST'])
def analyze_multiple():
    data = request.get_json()
    filepaths = data.get('filepaths', [])
    no_image = data.get('no_image', False)
    dense_mode = data.get('dense_mode', False)
    
    if not filepaths:
        return jsonify({'error': 'No files provided'}), 400
    
    system_prompt = get_system_prompt(dense_mode)
    
    all_analyses = []
    for filepath in filepaths:
        if not os.path.exists(filepath):
            continue
            
        results = reader.readtext(filepath)
        
        text_lines = []
        for idx, (bbox, text, confidence) in enumerate(results):
            x_coords = [float(p[0]) for p in bbox]
            y_coords = [float(p[1]) for p in bbox]
            text_lines.append({
                'id': int(idx),
                'text': text,
                'confidence': round(float(confidence), 3),
                'bbox': [[float(p[0]), float(p[1])] for p in bbox],
                'bbox_normalized': {
                    'x_min': min(x_coords),
                    'x_max': max(x_coords),
                    'y_min': min(y_coords),
                    'y_max': max(y_coords)
                }
            })
        
        text_lines.sort(key=lambda x: x['bbox_normalized']['y_min'])
        
        for i, line in enumerate(text_lines):
            line['id'] = i
        
        toon_data = encode({'lines': text_lines})
        
        if no_image:
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': f"Analyze this texting conversation (OCR data only):\n\n{toon_data}"}
                ],
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': 'text_evaluation',
                        'schema': EVALUATION_SCHEMA
                    }
                }
            )
        else:
            with open(filepath, 'rb') as img_file:
                img_base64 = base64.standard_b64encode(img_file.read()).decode('utf-8')
            
            response = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image_url',
                                'image_url': {
                                    'url': f'data:image/png;base64,{img_base64}'
                                }
                            },
                            {
                                'type': 'text',
                                'text': f"Analyze this texting conversation:\n\n{toon_data}"
                            }
                        ]
                    }
                ],
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': 'text_evaluation',
                        'schema': EVALUATION_SCHEMA
                    }
                }
            )
        
        content = response.choices[0].message.content or '{}'
        llm_result = json.loads(content)
        
        image_data = process_image(filepath, llm_result.get('groups', []), text_lines)
        
        all_analyses.append({
            'analysis_id': image_data['analysis_id'],
            'full_image': image_data['full_image'],
            'full_annotated': image_data['full_annotated'],
            'semi_annotated': image_data['semi_annotated'],
            'slices': image_data['slices'],
            'append_slices': image_data['append_slices'],
            'text_lines': text_lines,
            'analysis': llm_result
        })
    
    return jsonify({'analyses': all_analyses})


@app.route('/api/analyze-concatenated', methods=['POST'])
def analyze_concatenated():
    data = request.get_json()
    filepaths = data.get('filepaths', [])
    no_image = data.get('no_image', False)
    dense_mode = data.get('dense_mode', False)
    
    if not filepaths:
        return jsonify({'error': 'No files provided'}), 400
    
    valid_paths = [p for p in filepaths if os.path.exists(p)]
    if not valid_paths:
        return jsonify({'error': 'No valid files found'}), 400
    
    images = []
    max_width = 0
    for filepath in valid_paths:
        img = Image.open(filepath).convert('RGBA')
        images.append(img)
        max_width = max(max_width, img.width)
    
    total_height = sum(img.height for img in images)
    combined = Image.new('RGBA', (max_width, total_height), (255, 255, 255, 255))
    
    y_offset = 0
    for img in images:
        x_offset = (max_width - img.width) // 2
        combined.paste(img, (x_offset, y_offset))
        y_offset += img.height
    
    analysis_id = str(uuid.uuid4())[:8]
    combined_filename = f"{analysis_id}_combined.png"
    combined_path = os.path.join(ANALYSIS_FOLDER, combined_filename)
    combined.save(combined_path)
    
    results = reader.readtext(combined_path)
    
    text_lines = []
    for idx, (bbox, text, confidence) in enumerate(results):
        x_coords = [float(p[0]) for p in bbox]
        y_coords = [float(p[1]) for p in bbox]
        text_lines.append({
            'id': int(idx),
            'text': text,
            'confidence': round(float(confidence), 3),
            'bbox': [[float(p[0]), float(p[1])] for p in bbox],
            'bbox_normalized': {
                'x_min': min(x_coords),
                'x_max': max(x_coords),
                'y_min': min(y_coords),
                'y_max': max(y_coords)
            }
        })
    
    text_lines.sort(key=lambda x: x['bbox_normalized']['y_min'])
    
    for i, line in enumerate(text_lines):
        line['id'] = i
    
    toon_data = encode({'lines': text_lines})
    
    system_prompt = get_system_prompt(dense_mode)
    
    if no_image:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Analyze this texting conversation (OCR data only, multiple images concatenated):\n\n{toon_data}"}
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'text_evaluation',
                    'schema': EVALUATION_SCHEMA
                }
            }
        )
    else:
        with open(combined_path, 'rb') as img_file:
            img_base64 = base64.standard_b64encode(img_file.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/png;base64,{img_base64}'
                            }
                        },
                        {
                            'type': 'text',
                            'text': f"Analyze this texting conversation (multiple images concatenated into one):\n\n{toon_data}"
                        }
                    ]
                }
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': {
                    'name': 'text_evaluation',
                    'schema': EVALUATION_SCHEMA
                }
            }
        )
    
    content = response.choices[0].message.content or '{}'
    llm_result = json.loads(content)
    
    image_data = process_image(combined_path, llm_result.get('groups', []), text_lines)
    
    return jsonify({
        'analysis_id': image_data['analysis_id'],
        'full_image': image_data['full_image'],
        'full_annotated': image_data['full_annotated'],
        'semi_annotated': image_data['semi_annotated'],
        'slices': image_data['slices'],
        'append_slices': image_data['append_slices'],
        'text_lines': text_lines,
        'analysis': llm_result,
        'is_concatenated': True,
        'source_count': len(valid_paths)
    })


if __name__ == '__main__':
    app.run(debug=False, port=5000)