import os
import sys
import json
import random
import time
import webbrowser
from groq import Groq

def generate_filename_from_notes(client, model_name, notes_input):
    prompt = f"""Analyze the beginning of these study notes and respond with a single, brief theme name using lowercase letters and underscores (snake_case) only. Do not include spaces, file extensions, punctuation, or any introductory text. 

Examples:
- physics_kinematics
- ancient_roman_history
- cellular_respiration

Notes snippet:
{notes_input[:1500]}
"""
    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You output only a single snake_case string, no other text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=30000
        )
        theme = completion.choices[0].message.content.strip().lower()
        theme = "".join(c for c in theme if c.isalnum() or c == "_")
        return theme if theme else "study_quiz"
    except Exception:
        return "study_quiz"

def get_unique_filename(directory, base_name):
    filename = os.path.join(directory, f"{base_name}.html")
    counter = 1
    while os.path.exists(filename):
        filename = os.path.join(directory, f"{base_name}_{counter}.html")
        counter += 1
    return filename

def clean_and_deduplicate(questions_list):
    if not questions_list or not isinstance(questions_list, list):
        return [], 0

    seen_questions = set()
    deduplicated = []
    duplicate_count = 0

    for item in questions_list:
        if not all(k in item for k in ("question", "options", "correctIndex")):
            continue
        
        norm_q = " ".join(item["question"].strip().lower().split())
        
        if norm_q in seen_questions:
            duplicate_count += 1
            continue
            
        seen_questions.add(norm_q)
        deduplicated.append(item)
        
    return deduplicated, duplicate_count

def balance_and_shuffle_round(questions_list):
    if not questions_list:
        return []

    processed = []
    for item in questions_list:
        options = list(item["options"])
        orig_correct_text = options[item["correctIndex"]]
        random.shuffle(options)
        new_correct_index = options.index(orig_correct_text)
        
        processed.append({
            "question": item["question"],
            "options": options,
            "correctIndex": new_correct_index
        })

    random.shuffle(processed)
    flag_words = ["first", "1st", "second", "2nd", "third", "3rd"]
    balanced = []
    
    while processed:
        curr = processed.pop(0)
        if not balanced:
            balanced.append(curr)
            continue
            
        prev_q = balanced[-1]["question"].lower()
        curr_q = curr["question"].lower()
        
        is_sequential_clump = any(w in prev_q and w in curr_q for w in flag_words)
        is_repetitive_letter = balanced[-1]["correctIndex"] == curr["correctIndex"]
        
        if (is_sequential_clump or is_repetitive_letter) and len(processed) > 1:
            processed.insert(random.randint(1, len(processed)), curr)
        else:
            balanced.append(curr)
            
    return balanced

def get_groq_quiz_data(client, model_name, notes_input):
    base_tokens = 6000
    token_increment = 15000
    max_attempts = 5
    attempt = 1
    raw_json_text = ""

    while attempt <= max_attempts:
        current_max_tokens = base_tokens + ((attempt - 1) * token_increment)
        if attempt > 1:
            print(f"\n[!] Previous generation cut off due to token limits. Increasing max_tokens to {current_max_tokens} and trying again (Attempt {attempt}/{max_attempts})...")

        prompt = f"""
        You are an expert academic tutor and exam designer. 
        Analyze the provided raw study notes comprehensively. Based strictly on the concepts, facts, 
        mechanisms, names, and vocabulary found within them, generate TWO separate lists of multiple-choice questions.

        CRITICAL INSTRUCTION ON QUESTION QUANTITY AND GRANULARITY:
        - There is absolutely NO upper limit or cap on the number of questions. Maximize your output to cover every single fact.
        - Take advantage of descriptive lists, comparisons, and itemized properties. 
        - Break down all comparative facts into separate atomic questions. For example, if the text states "Person A is kind, Person B is not kind", you must extract at least TWO distinct questions: "Which person is kind?" and "Which person is not kind?". Do this across all matching structures.
        
        1. A list of standard multiple-choice questions covering all discovered details sequentially or exhaustively.
        2. A list of exactly 15 highly challenging, advanced-level "Sudden Death" multiple-choice questions focused on deep concept integration, trickier distinctions, or subtle details from the text.
        3. The questions must be completely randomized and must not follow any specific pattern in which questions are asked at what time. Try to avoid listing multiple questions in a row that have the same answer. However if you could take those questions that all have the same answer and mix them into the other generated questions, that would be awsome. I understand if the math doesn't align and you have to put two questions that have the same answer back to back.
        
        You MUST respond with a valid JSON object containing two keys: "standardQuestions" and "suddenDeathQuestions". 
        Do not include any markdown, backticks, or introductory text. Just the raw JSON object.
        
        Expected JSON Structure:
        {{
            "standardQuestions": [
                {{
                    "question": "The question text here...",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correctIndex": 0
                }}
            ],
            "suddenDeathQuestions": [
                {{
                    "question": "An advanced, harder question here...",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correctIndex": 2
                }}
            ]
        }}
        
        Note: 'correctIndex' is the 0-based index of the correct answer inside the 'options' array.

        Raw Notes Material:
        ---
        {notes_input}
        ---
        """

        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise study material analyzer that strictly outputs data in raw JSON format without markdown code blocks. Ensure your syntax finishes completely."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=current_max_tokens,
            )
            
            raw_json_text = completion.choices[0].message.content.strip()
            finish_reason = completion.choices[0].finish_reason
            
            if finish_reason == "length":
                attempt += 1
                continue
            else:
                break
                
        except Exception as api_err:
            print(f"\nFailed to get a response from Groq API: {api_err}")
            return None

    if not raw_json_text:
        return None

    if raw_json_text.startswith("```json"):
        raw_json_text = raw_json_text[7:]
    if raw_json_text.startswith("```"):
        raw_json_text = raw_json_text[3:]
    if raw_json_text.endswith("```"):
        raw_json_text = raw_json_text[:-3]
    raw_json_text = raw_json_text.strip()

    try:
        return json.loads(raw_json_text)
    except Exception as json_err:
        print("\nFailed to parse JSON directly from LLM response.")
        return None

def main():
    api_key = "Your_API_Key"
    model_name = "openai/gpt-oss-120b" 
    
    if not api_key:
        print("Error: API Key is missing.")
        return

    client = Groq(api_key=api_key)

    print("====================================================")
    print("        GROQ AI INTERACTIVE QUIZ APP GENERATOR      ")
    print("====================================================")
    print("Paste your notes below. When you are completely finished,")
    print("press Enter, then Ctrl+D (Mac/Linux) or Ctrl+Z followed by Enter (Windows)")
    print("to submit them to the AI agent.\n")
    print("Notes text:")
    
    try:
        notes_input = sys.stdin.read().strip()
    except Exception as e:
        print(f"Error reading input: {e}")
        return

    if not notes_input:
        print("No notes provided. Exiting program.")
        input("\nPress Enter to exit...")
        return

    print("\nProcessing your notes with Groq AI and creating your interactive web app... Please wait...")

    quiz_data_parsed = get_groq_quiz_data(client, model_name, notes_input)
    if not quiz_data_parsed:
        print("Failed to generate quiz content.")
        input("\nPress Enter to exit...")
        return

    standard_qs = quiz_data_parsed.get("standardQuestions", [])
    sudden_death_qs = quiz_data_parsed.get("suddenDeathQuestions", [])

    clean_standard, standard_dup_count = clean_and_deduplicate(standard_qs)
    clean_sudden, sudden_dup_count = clean_and_deduplicate(sudden_death_qs)

    print(f"\n[!] Deduplication Filter Active: Removed {standard_dup_count} duplicate question(s) from Standard Deck.")
    print(f"[!] Deduplication Filter Active: Removed {sudden_dup_count} duplicate question(s) from Sudden Death.")

    quiz_data_parsed["standardQuestions"] = balance_and_shuffle_round(clean_standard)
    quiz_data_parsed["suddenDeathQuestions"] = balance_and_shuffle_round(clean_sudden)

    shuffled_json_text = json.dumps(quiz_data_parsed)

    html_part_1 = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Active Recall Study App - Ultra Custom Edition</title>
    <style>
        :root {
            --bg-color: #f4f6f9;
            --text-color: #333333;
            --container-bg: #ffffff;
            --accent-color: #007bff;
            --accent-hover: #0056b3;
            --border-color: #e9ecef;
            --btn-bg: #f8f9fa;
            --btn-hover: #e2e6ea;
            --card-radius: 12px;
            --feedback-correct-bg: #d4edda;
            --feedback-correct-text: #155724;
            --feedback-incorrect-bg: #f8d7da;
            --feedback-incorrect-text: #721c24;
            --transition-speed: 0.2s;
            --glow-color: rgba(0, 123, 255, 0.2);
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            transition: background-color 0.3s ease, color 0.3s ease;
            position: relative;
        }
        
        body.sudden-death-mode {
            background-color: #2c1a1a !important;
            color: #f4f6f9 !important;
        }
        
        .quiz-container {
            background: var(--container-bg);
            padding: 30px;
            border-radius: var(--card-radius);
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            max-width: 600px;
            width: 100%;
            transition: all 0.3s ease;
            position: relative;
        }
        
        body.sudden-death-mode .quiz-container {
            background: #1e1212 !important;
            border: 2px solid #962d2d !important;
            box-shadow: 0 4px 25px rgba(255,0,0,0.2) !important;
        }
        
        h1 {
            color: var(--text-color);
            font-size: 24px;
            margin-top: 0;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 10px;
        }
        
        body.sudden-death-mode h1 {
            color: #e74c3c !important;
            border-bottom: 2px solid #3a1e1e !important;
        }
        
        .status {
            display: flex;
            justify-content: space-between;
            color: var(--text-color);
            opacity: 0.8;
            font-size: 14px;
            margin-bottom: 20px;
        }
        
        body.sudden-death-mode .status {
            color: #bc8f8f !important;
            opacity: 1;
        }
        
        .question {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
            line-height: 1.5;
        }
        
        .options-list {
            list-style-type: none;
            padding: 0;
        }
        
        .option-btn {
            display: block;
            width: 100%;
            background-color: var(--btn-bg);
            border: 2px solid var(--border-color);
            padding: 12px 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            text-align: left;
            font-size: 16px;
            cursor: pointer;
            transition: all var(--transition-speed) ease;
            color: var(--text-color);
        }
        
        body.sudden-death-mode .option-btn {
            background-color: #2a1b1b !important;
            border: 2px solid #442a2a !important;
            color: #f4f6f9 !important;
        }
        
        .option-btn:hover:not([disabled]) {
            background-color: var(--btn-hover);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px var(--glow-color);
        }
        
        body.sudden-death-mode .option-btn:hover:not([disabled]) {
            background-color: #3d2626 !important;
            border-color: #5c3a3a !important;
            box-shadow: 0 4px 8px rgba(231, 76, 60, 0.2);
        }
        
        .correct {
            background-color: var(--feedback-correct-bg) !important;
            border-color: #c3e6cb !important;
            color: var(--feedback-correct-text) !important;
            font-weight: bold;
        }
        
        body.sudden-death-mode .correct {
            background-color: #1b4322 !important;
            border-color: #2d6636 !important;
            color: #9bf0a7 !important;
        }
        
        .incorrect {
            background-color: var(--feedback-incorrect-bg) !important;
            border-color: #f5c6cb !important;
            color: var(--feedback-incorrect-text) !important;
        }
        
        body.sudden-death-mode .incorrect {
            background-color: #541c1c !important;
            border-color: #7a2828 !important;
            color: #ff9999 !important;
        }
        
        .feedback {
            margin-top: 15px;
            font-weight: 600;
            min-height: 24px;
        }
        
        .next-btn {
            display: block;
            width: 100%;
            background-color: var(--accent-color);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 20px;
            transition: background-color 0.2s, transform 0.1s;
        }
        
        .next-btn:hover {
            background-color: var(--accent-hover);
        }
        
        .next-btn:active {
            transform: scale(0.98);
        }
        
        body.sudden-death-mode .next-btn {
            background-color: #c0392b !important;
        }
        
        body.sudden-death-mode .next-btn:hover {
            background-color: #a93226 !important;
        }
        
        .action-layout-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 15px;
            margin-top: 20px;
        }
        
        .regen-btn {
            background-color: #e67e22 !important;
            color: white !important;
            width: 100%;
            border: none;
            padding: 10px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: background-color 0.2s;
            margin-top: 5px;
        }
        
        .regen-btn:hover {
            background-color: #d35400 !important;
        }

        .shuffle-btn {
            background-color: #9b59b6 !important;
            color: white !important;
            width: 100%;
            border: none;
            padding: 10px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: background-color 0.2s;
            margin-top: 5px;
        }
        
        .shuffle-btn:hover {
            background-color: #8e44ad !important;
        }
        
        .hidden {
            display: none !important;
        }
        
        .score-display {
            text-align: center;
            font-size: 22px;
            font-weight: bold;
            color: #27ae60;
            margin: 20px 0;
        }
        
        .fail-display {
            text-align: center;
            font-size: 24px;
            font-weight: bold;
            color: #e74c3c;
            margin: 20px 0;
        }

        .settings-toggle-btn {
            position: absolute;
            top: 15px;
            right: 15px;
            background: transparent;
            border: none;
            font-size: 24px;
            cursor: pointer;
            z-index: 1001;
            transition: transform 0.2s;
        }
        
        .settings-toggle-btn:hover {
            transform: rotate(45deg);
        }

        .settings-panel {
            position: fixed;
            top: 0;
            right: -340px;
            width: 300px;
            height: 100%;
            background: var(--container-bg);
            box-shadow: -2px 0 15px rgba(0,0,0,0.15);
            padding: 20px;
            transition: right 0.3s ease;
            z-index: 1000;
            overflow-y: auto;
            border-left: 1px solid var(--border-color);
        }

        .settings-panel.open {
            right: 0;
        }

        .settings-panel h3 {
            margin-top: 0;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 8px;
        }

        .setting-group {
            margin-bottom: 18px;
            border-bottom: 1px dashed var(--border-color);
            padding-bottom: 12px;
        }
        
        .setting-group:last-child {
            border-bottom: none;
        }

        .setting-group label {
            display: block;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 6px;
        }

        .setting-group input[type="color"] {
            width: 100%;
            height: 40px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            cursor: pointer;
            padding: 0;
        }

        .setting-group select, .setting-group input[type="text"], .setting-group input[type="number"] {
            width: 100%;
            padding: 8px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            background: var(--btn-bg);
            color: var(--text-color);
            box-sizing: border-box;
        }

        .switch {
            position: relative;
            display: inline-block;
            width: 50px;
            height: 24px;
        }

        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 24px;
        }

        .slider:before {
            position: absolute;
            content: "";
            height: 16px;
            width: 16px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }

        input:checked + .slider {
            background-color: #27ae60;
        }

        input:checked + .slider:before {
            transform: translateX(26px);
        }
        
        .timer-bar-container {
            width: 100%;
            background-color: var(--border-color);
            height: 6px;
            border-radius: 3px;
            margin-bottom: 15px;
            overflow: hidden;
        }
        
        .timer-bar {
            height: 100%;
            background-color: var(--accent-color);
            width: 100%;
            transition: width 0.1s linear;
        }
        
        .facts-card {
            background-color: var(--btn-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 15px;
            margin-top: 15px;
            max-height: 200px;
            overflow-y: auto;
            text-align: left;
        }
        
        .facts-card h4 {
            margin-top: 0;
            margin-bottom: 8px;
            color: var(--accent-color);
        }
        
        .facts-card ul {
            margin: 0;
            padding-left: 20px;
            font-size: 14px;
            line-height: 1.4;
        }
        
        .facts-card li {
            margin-bottom: 6px;
        }

        /* Sound Effect Notification Toast Placeholder */
        .toast {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.8);
            color: #fff;
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            z-index: 2000;
            opacity: 0;
            transition: opacity 0.3s ease;
            pointer-events: none;
        }
        .toast.show {
            opacity: 1;
        }
    </style>
</head>
<body>

<button class="settings-toggle-btn" onclick="toggleSettings()" title="Settings">⚙️</button>

<div class="toast" id="quiz-toast"></div>

<div class="settings-panel" id="settings-panel">
    <h3>Configuration Panel</h3>
    
    <!-- ORIGINAL SETTINGS (Do not overwrite) -->
    <div class="setting-group">
        <label>Background Color</label>
        <input type="color" id="setting-bg-color" value="#f4f6f9" onchange="updateColors()">
    </div>
    
    <div class="setting-group">
        <label>Text/Main Color</label>
        <input type="color" id="setting-text-color" value="#333333" onchange="updateColors()">
    </div>
    
    <div class="setting-group">
        <label>Container Theme</label>
        <select id="setting-container-theme" onchange="updateContainerTheme()">
            <option value="light">Light Mode</option>
            <option value="dark">Dark Mode</option>
            <option value="sepia">Sepia Style</option>
        </select>
    </div>

    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;">Allow Sudden Death Round</label>
        <label class="switch">
            <input type="checkbox" id="setting-sudden-death-toggle" checked onchange="handleSuddenDeathToggle()">
            <span class="slider"></span>
        </label>
    </div>

    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;">Enable Question Timer</label>
        <label class="switch">
            <input type="checkbox" id="setting-timer-toggle" onchange="toggleTimerSetting()">
            <span class="slider"></span>
        </label>
    </div>

    <div class="setting-group" id="timer-duration-group" style="display: none;">
        <label>Timer Duration (seconds)</label>
        <input type="number" id="setting-timer-duration" value="15" min="5" max="60">
    </div>

    <div class="setting-group">
        <label>Font Size</label>
        <select id="setting-font-size" onchange="updateFontSize()">
            <option value="14px">Small</option>
            <option value="18px" selected>Normal</option>
            <option value="22px">Large</option>
        </select>
    </div>

    <div class="setting-group">
        <label>Deck Manipulation Actions</label>
        <button onclick="shuffleCurrentDeck()" class="shuffle-btn">🔀 Shuffle Current Deck</button>
        <button onclick="regenerateFacts()" class="regen-btn">Regenerate Core Facts</button>
    </div>

    <!-- NEW CREATIVE ADDED SETTINGS -->
    <h4>✨ Advanced Gameplay Settings</h4>
    
    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;" title="Instantly filters options down to 2 choices when a question loads.">50:50 Lifeline Mode</label>
        <label class="switch">
            <input type="checkbox" id="setting-fifty-fifty" onchange="toggleFiftyFifty()">
            <span class="slider"></span>
        </label>
    </div>

    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;" title="Provides a point penalty for incorrect answers.">Penalty Mode (-1pt / Error)</label>
        <label class="switch">
            <input type="checkbox" id="setting-penalty-mode">
            <span class="slider"></span>
        </label>
    </div>

    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;" title="Enables synth sound effect notes on selection.">Audio Cue Text Effects</label>
        <label class="switch">
            <input type="checkbox" id="setting-audio-cues" checked>
            <span class="slider"></span>
        </label>
    </div>

    <div class="setting-group">
        <label title="Limit the standard session length to a custom subset of questions.">Standard Session Question Limit</label>
        <select id="setting-question-limit" onchange="changeQuestionLimit()">
            <option value="all" selected>All Generated Questions</option>
            <option value="5">5 Questions</option>
            <option value="10">10 Questions</option>
            <option value="20">20 Questions</option>
            <option value="50">50 Questions</option>
        </select>
    </div>

    <div class="setting-group">
        <label>Accent Highlights Theme</label>
        <select id="setting-accent-theme" onchange="updateAccentTheme()">
            <option value="#007bff" selected>Default Royal Blue</option>
            <option value="#2ecc71">Emerald Study Green</option>
            <option value="#9b59b6">Amethyst Purple</option>
            <option value="#e67e22">Carrot Orange</option>
            <option value="#e74c3c">Crimson Red</option>
        </select>
    </div>

    <div class="setting-group">
        <label>UI Corners (Border Radius)</label>
        <select id="setting-border-radius" onchange="updateBorderRadius()">
            <option value="12px" selected>Rounded Cards</option>
            <option value="0px">Sharp Sharp/Retro</option>
            <option value="24px">Ultra Smooth Bubble</option>
        </select>
    </div>

    <div class="setting-group">
        <label>Font Typography style</label>
        <select id="setting-font-family" onchange="updateFontFamily()">
            <option value="Segoe UI" selected>Modern Sans-Serif</option>
            <option value="Georgia">Academic Serif</option>
            <option value="Courier New">Developer Monospace</option>
            <option value="Comic Sans MS">Casual / Friendly</option>
        </select>
    </div>

    <div class="setting-group" style="display: flex; justify-content: space-between; align-items: center;">
        <label style="margin-bottom: 0;" title="Hides the real-time score tracker.">Incognito Blind Scoring</label>
        <label class="switch">
            <input type="checkbox" id="setting-blind-scoring" onchange="toggleBlindScoring()">
            <span class="slider"></span>
        </label>
    </div>
</div>

<div class="quiz-container">
    <h1 id="app-title">Active Recall Study App</h1>
    
    <div class="timer-bar-container hidden" id="timer-container">
        <div class="timer-bar" id="timer-bar"></div>
    </div>
    
    <div id="quiz-box">
        <div class="status">
            <span id="question-number">Question 1 of 10</span>
            <span id="score-tracker">Score: 0</span>
        </div>
        
        <div class="question" id="question-text">Loading question...</div>
        
        <div class="options-list" id="options-container"></div>
        
        <div class="feedback" id="feedback-text"></div>
        
        <button id="next-button" class="next-btn hidden">Next Question →</button>
    </div>

    <div id="result-box" class="hidden">
        <h2 id="result-heading">Session Complete!</h2>
        <div class="score-display" id="final-score">0 / 0</div>
        <p id="result-text">Excellent work! Your brain is strengthening its recall pathways.</p>
        
        <div class="facts-card" id="facts-card-display">
            <h4>💡 Extracted Brain Insights</h4>
            <ul id="facts-list-container">
                <li>Open the settings menu (⚙️) and click "Regenerate Core Facts" to synthesize a brand new flash list derived from the deck repository context!</li>
            </ul>
        </div>
        
        <div class="action-layout-grid">
            <button onclick="restartQuiz()" class="next-btn">Retake Quiz</button>
        </div>
    </div>
</div>

<script type="application/json" id="quiz-json-data">"""

    html_part_2 = shuffled_json_text

    html_part_3 = """</script>

<script>
    const serverData = JSON.parse(document.getElementById('quiz-json-data').textContent);
    const rawStandardQuestions = serverData.standardQuestions || [];
    const suddenDeathQuestions = serverData.suddenDeathQuestions || [];

    let masterStandardList = [...rawStandardQuestions];
    let currentQuestionsList = [];
    let currentQuestionIndex = 0;
    let score = 0;
    let answered = false;
    let mode = "standard"; 
    let suddenDeathIndex = 0;
    
    let timerInterval = null;
    let timeRemaining = 0;
    let totalTimeAllocated = 15;

    const body = document.body;
    const appTitle = document.getElementById('app-title');
    const questionText = document.getElementById('question-text');
    const optionsContainer = document.getElementById('options-container');
    const questionNumber = document.getElementById('question-number');
    const scoreTracker = document.getElementById('score-tracker');
    const feedbackText = document.getElementById('feedback-text');
    const nextButton = document.getElementById('next-button');
    const quizBox = document.getElementById('quiz-box');
    const resultBox = document.getElementById('result-box');
    const finalScore = document.getElementById('final-score');
    const resultHeading = document.getElementById('result-heading');
    const resultText = document.getElementById('result-text');
    const timerContainer = document.getElementById('timer-container');
    const timerBar = document.getElementById('timer-bar');
    const factsListContainer = document.getElementById('facts-list-container');
    const toast = document.getElementById('quiz-toast');

    // Build standard list initially based on limits
    initializeQuestionDeck();

    function showToast(message) {
        toast.textContent = message;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1500);
    }

    function playAudioTone(type) {
        if (!document.getElementById('setting-audio-cues').checked) return;
        try {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            
            if (type === 'correct') {
                oscillator.type = 'sine';
                oscillator.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
                oscillator.frequency.setValueAtTime(880, audioCtx.currentTime + 0.1); // A5
                gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
                oscillator.start();
                oscillator.stop(audioCtx.currentTime + 0.25);
            } else if (type === 'incorrect') {
                oscillator.type = 'sawtooth';
                oscillator.frequency.setValueAtTime(220, audioCtx.currentTime); // A3
                oscillator.frequency.setValueAtTime(146.83, audioCtx.currentTime + 0.15); // D3
                gainNode.gain.setValueAtTime(0.08, audioCtx.currentTime);
                oscillator.start();
                oscillator.stop(audioCtx.currentTime + 0.3);
            }
        } catch(e) { console.log("WebAudio context block or unsupported:", e); }
    }

    function initializeQuestionDeck() {
        const limitVal = document.getElementById('setting-question-limit').value;
        const suddenDeathAllowed = document.getElementById('setting-sudden-death-toggle').checked;
        
        if (limitVal === 'all') {
            masterStandardList = [...rawStandardQuestions];
        } else {
            const numericLimit = parseInt(limitVal);
            masterStandardList = rawStandardQuestions.slice(0, numericLimit);
        }

        if (mode === "standard") {
            if (!suddenDeathAllowed) {
                currentQuestionsList = [...masterStandardList, ...suddenDeathQuestions];
            } else {
                currentQuestionsList = [...masterStandardList];
            }
        }
    }

    function changeQuestionLimit() {
        initializeQuestionDeck();
        restartQuiz();
        showToast("Session length updated!");
    }

    function toggleFiftyFifty() {
        loadQuestion();
        if (document.getElementById('setting-fifty-fifty').checked) {
            showToast("50:50 Lifeline Active!");
        }
    }

    function toggleBlindScoring() {
        toggleBlindScoringVisibility();
    }

    function toggleBlindScoringVisibility() {
        const blindActive = document.getElementById('setting-blind-scoring').checked;
        if (blindActive) {
            scoreTracker.style.visibility = 'hidden';
        } else {
            scoreTracker.style.visibility = 'visible';
        }
    }

    function updateAccentTheme() {
        const accentColor = document.getElementById('setting-accent-theme').value;
        document.documentElement.style.setProperty('--accent-color', accentColor);
        // Calculate hover dynamic tint color shifts
        if(accentColor === "#2ecc71") document.documentElement.style.setProperty('--accent-hover', '#27ae60');
        else if(accentColor === "#9b59b6") document.documentElement.style.setProperty('--accent-hover', '#8e44ad');
        else if(accentColor === "#e67e22") document.documentElement.style.setProperty('--accent-hover', '#d35400');
        else if(accentColor === "#e74c3c") document.documentElement.style.setProperty('--accent-hover', '#c0392b');
        else document.documentElement.style.setProperty('--accent-hover', '#0056b3');
    }

    function updateBorderRadius() {
        const radius = document.getElementById('setting-border-radius').value;
        document.documentElement.style.setProperty('--card-radius', radius);
    }

    function updateFontFamily() {
        const font = document.getElementById('setting-font-family').value;
        document.body.style.fontFamily = font + ", sans-serif";
    }

    function handleSuddenDeathToggle() {
        initializeQuestionDeck();
        if (mode === "standard") {
            if (currentQuestionIndex >= currentQuestionsList.length && currentQuestionsList.length > 0) {
                currentQuestionIndex = currentQuestionsList.length - 1;
            }
            if (currentQuestionsList.length > 0) {
                questionNumber.textContent = `Standard Round: Question ${currentQuestionIndex + 1} of ${currentQuestionsList.length}`;
            }
        }
    }

    function shuffleCurrentDeck() {
        if (!currentQuestionsList || currentQuestionsList.length <= 1) return;
        
        let remainingQuestions = currentQuestionsList.slice(currentQuestionIndex);
        
        for (let i = remainingQuestions.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [remainingQuestions[i], remainingQuestions[j]] = [remainingQuestions[j], remainingQuestions[i]];
        }
        
        remainingQuestions.forEach(item => {
            if (item.options && item.options.length > 1) {
                let optionsArray = [...item.options];
                let correctText = optionsArray[item.correctIndex];
                
                for (let i = optionsArray.length - 1; i > 0; i--) {
                    const j = Math.floor(Math.random() * (i + 1));
                    [optionsArray[i], optionsArray[j]] = [optionsArray[j], optionsArray[i]];
                }
                
                item.options = optionsArray;
                item.correctIndex = optionsArray.indexOf(correctText);
            }
        });
        
        currentQuestionsList = currentQuestionsList.slice(0, currentQuestionIndex).concat(remainingQuestions);
        showToast("Deck dynamically shuffled!");
        loadQuestion();
    }

    function toggleSettings() {
        document.getElementById('settings-panel').classList.toggle('open');
    }

    function updateColors() {
        const bgColor = document.getElementById('setting-bg-color').value;
        const textColor = document.getElementById('setting-text-color').value;
        document.documentElement.style.setProperty('--bg-color', bgColor);
        document.documentElement.style.setProperty('--text-color', textColor);
    }

    function updateContainerTheme() {
        const theme = document.getElementById('setting-container-theme').value;
        if (theme === 'dark') {
            document.documentElement.style.setProperty('--container-bg', '#1e293b');
            document.documentElement.style.setProperty('--border-color', '#334155');
            document.documentElement.style.setProperty('--btn-bg', '#334155');
            document.documentElement.style.setProperty('--btn-hover', '#475569');
            document.documentElement.style.setProperty('--text-color', '#f8f9fa');
            document.documentElement.style.setProperty('--feedback-correct-bg', '#1e3a1e');
            document.documentElement.style.setProperty('--feedback-correct-text', '#a3f3a3');
            document.documentElement.style.setProperty('--feedback-incorrect-bg', '#4a1e1e');
            document.documentElement.style.setProperty('--feedback-incorrect-text', '#fca5a5');
        } else if (theme === 'sepia') {
            document.documentElement.style.setProperty('--container-bg', '#f4ecd8');
            document.documentElement.style.setProperty('--border-color', '#e4d5b7');
            document.documentElement.style.setProperty('--btn-bg', '#ebdcb9');
            document.documentElement.style.setProperty('--btn-hover', '#decb9e');
            document.documentElement.style.setProperty('--text-color', '#433422');
            document.documentElement.style.setProperty('--feedback-correct-bg', '#d1e7dd');
            document.documentElement.style.setProperty('--feedback-correct-text', '#0f5132');
            document.documentElement.style.setProperty('--feedback-incorrect-bg', '#f8d7da');
            document.documentElement.style.setProperty('--feedback-incorrect-text', '#842029');
        } else {
            document.documentElement.style.setProperty('--container-bg', '#ffffff');
            document.documentElement.style.setProperty('--border-color', '#e9ecef');
            document.documentElement.style.setProperty('--btn-bg', '#f8f9fa');
            document.documentElement.style.setProperty('--btn-hover', '#e2e6ea');
            document.documentElement.style.setProperty('--text-color', '#333333');
            document.documentElement.style.setProperty('--feedback-correct-bg', '#d4edda');
            document.documentElement.style.setProperty('--feedback-correct-text', '#155724');
            document.documentElement.style.setProperty('--feedback-incorrect-bg', '#f8d7da');
            document.documentElement.style.setProperty('--feedback-incorrect-text', '#721c24');
        }
    }

    function updateFontSize() {
        const size = document.getElementById('setting-font-size').value;
        document.getElementById('question-text').style.fontSize = size;
    }

    function toggleTimerSetting() {
        const timerEnabled = document.getElementById('setting-timer-toggle').checked;
        document.getElementById('timer-duration-group').style.display = timerEnabled ? 'block' : 'none';
    }

    function startTimer() {
        clearInterval(timerInterval);
        const timerEnabled = document.getElementById('setting-timer-toggle').checked;
        if (!timerEnabled) {
            timerContainer.classList.add('hidden');
            return;
        }
        
        totalTimeAllocated = parseInt(document.getElementById('setting-timer-duration').value) || 15;
        timeRemaining = totalTimeAllocated;
        timerContainer.classList.remove('hidden');
        timerBar.style.width = '100%';
        
        timerInterval = setInterval(() => {
            timeRemaining -= 0.1;
            const percentage = (timeRemaining / totalTimeAllocated) * 100;
            timerBar.style.width = `${percentage}%`;
            
            if (timeRemaining <= 0) {
                clearInterval(timerInterval);
                handleTimeOut();
            }
        }, 100);
    }

    function handleTimeOut() {
        if (answered) return;
        answered = true;
        playAudioTone('incorrect');
        
        const currentData = currentQuestionsList[currentQuestionIndex];
        const buttons = optionsContainer.getElementsByClassName('option-btn');
        
        for (let i = 0; i < buttons.length; i++) {
            buttons[i].disabled = true;
            if (parseInt(buttons[i].getAttribute('data-index')) === currentData.correctIndex) {
                buttons[i].classList.add('correct');
            }
        }
        
        if (document.getElementById('setting-penalty-mode').checked && mode === "standard") {
            score--;
        }
        
        feedbackText.textContent = "⏱️ Time's up!";
        feedbackText.className = "feedback incorrect";
        scoreTracker.textContent = `Score: ${score}`;
        
        if (mode === "standard") {
            nextButton.classList.remove('hidden');
        } else {
            setTimeout(() => { showResults(false); }, 1500);
        }
    }

    function loadQuestion() {
        answered = false;
        feedbackText.textContent = "";
        feedbackText.className = "feedback";
        nextButton.classList.add('hidden');
        toggleBlindScoringVisibility();
        
        if (currentQuestionsList.length === 0) {
            questionText.textContent = "No questions found.";
            return;
        }
        
        const currentData = currentQuestionsList[currentQuestionIndex];
        
        if (mode === "standard") {
            questionNumber.textContent = `Standard Round: Question ${currentQuestionIndex + 1} of ${currentQuestionsList.length}`;
            scoreTracker.textContent = `Score: ${score}`;
        } else {
            questionNumber.textContent = `SUDDEN DEATH: Question ${suddenDeathIndex + 1} of ${currentQuestionsList.length}`;
            scoreTracker.textContent = `Streak: ${suddenDeathIndex}`;
        }
        
        questionText.textContent = currentData.question;
        
        optionsContainer.innerHTML = "";
        
        // 50:50 Lifeline calculation processing
        let hiddenIndices = [];
        if (document.getElementById('setting-fifty-fifty').checked && currentData.options.length > 2) {
            let incorrectIndices = [];
            currentData.options.forEach((_, idx) => {
                if (idx !== currentData.correctIndex) incorrectIndices.push(idx);
            });
            // Shuffle and pick items to hide leaving exactly 1 incorrect + 1 correct
            incorrectIndices.sort(() => 0.5 - Math.random());
            hiddenIndices = incorrectIndices.slice(0, currentData.options.length - 2);
        }

        currentData.options.forEach((option, index) => {
            const button = document.createElement('button');
            button.className = 'option-btn';
            button.textContent = option;
            button.setAttribute('data-index', index);
            button.onclick = () => selectOption(index);
            
            if (hiddenIndices.includes(index)) {
                button.classList.add('hidden');
            }
            
            optionsContainer.appendChild(button);
        });
        
        startTimer();
    }

    function selectOption(selectedIndex) {
        if (answered) return;
        answered = true;
        clearInterval(timerInterval);
        
        const currentData = currentQuestionsList[currentQuestionIndex];
        const buttons = optionsContainer.getElementsByClassName('option-btn');
        
        let selectedButton = null;
        let correctButton = null;
        
        for (let i = 0; i < buttons.length; i++) {
            buttons[i].disabled = true;
            let bIdx = parseInt(buttons[i].getAttribute('data-index'));
            if (bIdx === selectedIndex) selectedButton = buttons[i];
            if (bIdx === currentData.correctIndex) correctButton = buttons[i];
        }
        
        if (selectedIndex === currentData.correctIndex) {
            playAudioTone('correct');
            if (selectedButton) selectedButton.classList.add('correct');
            feedbackText.textContent = "Correct! ✨";
            feedbackText.classList.add('correct');
            
            if (mode === "standard") {
                score++;
                scoreTracker.textContent = `Score: ${score}`;
                nextButton.classList.remove('hidden');
            } else {
                suddenDeathIndex++;
                feedbackText.textContent = "Correct! Moving to next Sudden Death question... ⚡";
                setTimeout(() => {
                    currentQuestionIndex++;
                    if (currentQuestionIndex < currentQuestionsList.length) {
                        loadQuestion();
                    } else {
                        showResults(true); 
                    }
                }, 1500);
            }
        } else {
            playAudioTone('incorrect');
            if (selectedButton) selectedButton.classList.add('incorrect');
            if (correctButton) correctButton.classList.add('correct');
            
            if (mode === "standard") {
                if (document.getElementById('setting-penalty-mode').checked) {
                    score--;
                }
                feedbackText.textContent = "Incorrect. Review the correct answer highlighted above.";
                feedbackText.classList.add('incorrect');
                scoreTracker.textContent = `Score: ${score}`;
                nextButton.classList.remove('hidden');
            } else {
                feedbackText.textContent = "WRONG! Sudden Death Eliminated! 💀";
                feedbackText.classList.add('incorrect');
                setTimeout(() => {
                    showResults(false); 
                }, 2000);
            }
        }
    }

    nextButton.onclick = () => {
        currentQuestionIndex++;
        if (currentQuestionIndex < currentQuestionsList.length) {
            loadQuestion();
        } else {
            const suddenDeathAllowed = document.getElementById('setting-sudden-death-toggle').checked;
            if (mode === "standard" && suddenDeathQuestions.length > 0 && suddenDeathAllowed) {
                startSuddenDeathRound();
            } else {
                showResults(true);
            }
        }
    };

    function startSuddenDeathRound() {
        alert("⚠️ WARNING: Standard Round Complete! Entering 15-Question Hard Sudden Death Round. One wrong answer means instant elimination!");
        mode = "sudden_death";
        currentQuestionsList = suddenDeathQuestions;
        currentQuestionIndex = 0;
        suddenDeathIndex = 0;
        
        body.classList.add('sudden-death-mode');
        appTitle.textContent = "SUDDEN DEATH HARD ROUND ⚡";
        loadQuestion();
    }

    function showResults(completedQuiz) {
        clearInterval(timerInterval);
        timerContainer.classList.add('hidden');
        quizBox.classList.add('hidden');
        resultBox.classList.remove('hidden');
        scoreTracker.style.visibility = 'visible'; 
        
        if (mode === "standard") {
            finalScore.className = "score-display";
            finalScore.textContent = `${score} / ${currentQuestionsList.length}`;
            resultHeading.textContent = "Session Complete!";
            resultText.textContent = "Excellent work! Your brain is strengthening its recall pathways.";
        } else {
            if (completedQuiz) {
                finalScore.className = "score-display";
                finalScore.textContent = `🏆 PERFECT RUN: ${score} Standard + ${suddenDeathQuestions.length} Sudden Death`;
                resultHeading.textContent = "GOD MODE UNLOCKED!";
                resultText.textContent = "Incredible! You survived all 15 custom sudden death hard questions without a single mistake!";
            } else {
                finalScore.className = "fail-display";
                finalScore.textContent = `ELIMINATED at Sudden Death Question ${suddenDeathIndex + 1}`;
                resultHeading.textContent = "Game Over!";
                resultText.textContent = `You finished the standard round with scoring points, but fell during sudden death challenge. Try again to beat your streak!`;
            }
        }
        
        factsListContainer.innerHTML = "<li>Open the settings menu (⚙️) and click 'Regenerate Core Facts' to synthesize a brand new randomized flash list derived from the active question deck!</li>";
    }

    function regenerateFacts() {
        if (!currentQuestionsList || currentQuestionsList.length === 0) return;
        
        factsListContainer.innerHTML = "<li>Synthesizing fresh flash insights...</li>";
        
        let pool = [...currentQuestionsList];
        let selectedFacts = [];
        
        pool.sort(() => 0.5 - Math.random());
        let count = Math.min(5, pool.length);
        
        for(let i=0; i<count; i++) {
            let qItem = pool[i];
            let correctOptionText = qItem.options[qItem.correctIndex];
            
            let statement = `Core Fact: For "${qItem.question}", the accurate verification is: <strong>${correctOptionText}</strong>.`;
            selectedFacts.push(statement);
        }
        
        setTimeout(() => {
            factsListContainer.innerHTML = "";
            selectedFacts.forEach(fact => {
                let li = document.createElement('li');
                li.innerHTML = fact;
                factsListContainer.appendChild(li);
            });
            showToast("Brain insights synthesized!");
        }, 400);
    }

    function restartQuiz() {
        mode = "standard";
        initializeQuestionDeck();
        currentQuestionIndex = 0;
        score = 0;
        suddenDeathIndex = 0;
        
        body.classList.remove('sudden-death-mode');
        appTitle.textContent = "Active Recall Study App";
        resultBox.classList.add('hidden');
        quizBox.classList.remove('hidden');
        loadQuestion();
    }

    if (currentQuestionsList && currentQuestionsList.length > 0) {
        loadQuestion();
    } else {
        questionText.textContent = "No questions found.";
    }
</script>
</body>
</html>
"""

    html_template = html_part_1 + html_part_2 + html_part_3

    output_dir = r"Your_Desired_Quiz_Location_This_Will_Set_Location_Of_Ouputed_Quiz"
    os.makedirs(output_dir, exist_ok=True)
    
    base_name = generate_filename_from_notes(client, model_name, notes_input)
    output_filename = get_unique_filename(output_dir, base_name)
    full_path = os.path.join(output_dir, output_filename)

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(html_template)
        print(f"\n[+] Success! Custom quiz web application generated seamlessly.")
        print(f"[+] Local Output File Path: {full_path}")
        
        try:
            webbrowser.open(os.path.abspath(full_path))
            print("[+] Automatically launching quiz app in your web browser...")
        except Exception as browser_err:
            print(f"[!] Unable to open browser automatically: {browser_err}")
            
    except Exception as file_err:
        print(f"\nError writing output file: {file_err}")

if __name__ == "__main__":
    main()
