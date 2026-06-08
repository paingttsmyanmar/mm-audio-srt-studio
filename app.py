import gradio as gr
import asyncio
import edge_tts
import re
import os
import datetime
import json
from huggingface_hub import HfApi

try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent
except ImportError:
    raise ImportError("ကျေးဇူးပြု၍ requirements.txt တွင် pydub ထည့်ပေးပါ။")

DATASET_REPO = "Paing1213/vip-database-storage"
DB_FILE = "vip_database.json"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
HF_TOKEN = os.environ.get("HF_TOKEN")
api = HfApi(token=HF_TOKEN)

def load_vip_database():
    if not HF_TOKEN or not os.path.exists(DB_FILE):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
            except: return {}
        return {}
    try:
        from huggingface_hub import hf_hub_download
        filepath = hf_hub_download(repo_id=DATASET_REPO, filename=DB_FILE, repo_type="dataset", token=HF_TOKEN)
        with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_vip_database(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    if HF_TOKEN:
        try:
            try: api.create_repo(repo_id=DATASET_REPO, repo_type="dataset", private=True, exist_ok=True)
            except: pass
            api.upload_file(path_or_fileobj=DB_FILE, path_in_repo=DB_FILE, repo_id=DATASET_REPO, repo_type="dataset")
        except: pass

VIP_PASSWORDS = load_vip_database()

def register_or_renew_vip(admin_pass, user_password, days_to_add):
    global VIP_PASSWORDS
    if admin_pass.strip() != ADMIN_PASSWORD: return "❌ Admin Password မမှန်ကန်ပါ။"
    u_pass = user_password.strip()
    if not u_pass: return "⚠️ User Password ရိုက်ထည့်ပါ။"

    VIP_PASSWORDS = load_vip_database()
    current_time = datetime.datetime.now()
    if u_pass in VIP_PASSWORDS:
        try:
            old_expiry = datetime.datetime.strptime(VIP_PASSWORDS[u_pass]["valid_until"], "%Y-%m-%d")
            new_expiry = (old_expiry if old_expiry > current_time else current_time) + datetime.timedelta(days=int(days_to_add))
        except: new_expiry = current_time + datetime.timedelta(days=int(days_to_add))
    else: new_expiry = current_time + datetime.timedelta(days=int(days_to_add))

    VIP_PASSWORDS[u_pass] = {"valid_until": new_expiry.strftime("%Y-%m-%d")}
    save_vip_database(VIP_PASSWORDS)
    return f"✅ အောင်မြင်ပါသည်။ Password [{u_pass}] အား {new_expiry.strftime('%Y-%m-%d')} အထိ VIP တိုးလိုက်ပါပြီ။"

def check_vip_status_ui():
    db = load_vip_database()
    if not db: return "ယခုလက်ရှိတွင် VIP User မရှိသေးပါ။"
    out = "📋 လက်ရှိ VIP စာရင်း -\n\n"
    for k, v in db.items(): out += f"🔑 Password: {k} | 📅 ကုန်ရက်: {v['valid_until']}\n"
    return out

def format_srt_time(seconds):
    if seconds < 0: seconds = 0
    millis = int(seconds * 1000)
    hours = millis // 3600000
    millis %= 3600000
    minutes = millis // 60000
    millis %= 60000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def segment_myanmar_text(raw_text, max_chars=40):
    for char in ["“", "”", '"', "‘", "’", "'", "--", "—", "…"]:
        raw_text = raw_text.replace(char, " ")
    
    raw_text = re.sub(r"[ \t]+", " ", raw_text).strip()
    split_pattern = re.split(r'([။၊!?\n]+)', raw_text)
    
    temp_chunks = []
    current_chunk = ""
    
    for item in split_pattern:
        current_chunk += item
        if any(p in item for p in ['။', '၊', '?', '!', '\n']):
            clean_chunk = current_chunk.strip()
            if len(re.sub(r'[\s၊။!?\-\"\']', '', clean_chunk)) > 0: 
                temp_chunks.append(clean_chunk)
            current_chunk = ""
            
    if current_chunk.strip():
        clean_chunk = current_chunk.strip()
        if len(re.sub(r'[\s၊။!?\-\"\']', '', clean_chunk)) > 0: 
            temp_chunks.append(clean_chunk)
            
    final_segments = []
    for chunk in temp_chunks:
        if len(chunk) <= max_chars:
            final_segments.append(chunk)
        else:
            sub_words = chunk.split(' ')
            line_buffer = ""
            for word in sub_words:
                if len(line_buffer) + len(word) + 1 <= max_chars:
                    line_buffer += (" " if line_buffer else "") + word
                else:
                    if line_buffer: final_segments.append(line_buffer.strip())
                    if len(word) > max_chars:
                        for i in range(0, len(word), max_chars):
                            final_segments.append(word[i:i+max_chars])
                        line_buffer = ""
                    else:
                        line_buffer = word
            if line_buffer:
                final_segments.append(line_buffer.strip())
                
    return final_segments

async def process_voice_generation(
    text, surveyed_text, filename, s1_voice, s2_voice, s3_voice,
    style, srt_type, tone, speed, volume, progress=gr.Progress()
):
    if not text.strip(): return None, None, None, gr.update(visible=False)

    processed_text = text.replace("--", " ").replace("—", " ").replace("…", " ")
    
    if surveyed_text.strip():
        for line in surveyed_text.strip().split("\n"):
            if "=" in line: key, val = line.split("=", 1); processed_text = processed_text.replace(key.strip(), val.strip())

    voice_map = {"သီဟ (🇲🇲 - ကျား)": "my-MM-ThihaNeural", "နီလာ (🇲🇲 - မ)": "my-MM-NilarNeural", "စမူပိုင်ကြီး (🇲🇲 - ကျား)": "my-MM-ThihaNeural"}
    selected_voice = voice_map.get(s1_voice, "my-MM-ThihaNeural")
    base_speed = speed + 20
    speed_rate = f"{'+' if base_speed >= 0 else ''}{base_speed}%"
    volume_rate = f"+{volume}%"

    output_name = filename.strip() if filename.strip() else "Myanmar_TTS"
    output_mp3 = f"{output_name}.mp3"
    output_srt = f"{output_name}.srt"

    max_srt_chars = 40 if srt_type == "TikTok" else 70
    sentences = segment_myanmar_text(processed_text, max_chars=max_srt_chars)
    total_sentences = len(sentences)
    
    if total_sentences == 0:
        return None, None, None, gr.update(visible=False)

    progress(0.2, desc=f"⏳ စာသားများကို အသံအဖြစ် ပြောင်းလဲနေပါသည် ({total_sentences} ကြောင်း)...")

    sem = asyncio.Semaphore(15)

    async def fetch_audio(idx, sentence):
        async with sem:
            try:
                communicate = edge_tts.Communicate(
                    text=sentence, voice=selected_voice, rate=speed_rate, volume=volume_rate
                )
                chunk_audio = bytearray()
                async for msg in communicate.stream():
                    if msg["type"] == "audio":
                        chunk_audio.extend(msg["data"])
                return idx, chunk_audio
            except Exception as e:
                print(f"Skipping server error on sentence {idx}: {e}")
                return idx, b""

    tasks = [fetch_audio(idx, s) for idx, s in enumerate(sentences)]
    audio_results = await asyncio.gather(*tasks)
    
    audio_results.sort(key=lambda x: x[0])

    progress(0.7, desc="⚙️ အသံနှင့် စာတန်းထိုးကို အချောသတ် ချိန်ညှိနေပါသည်...")

    combined_audio = AudioSegment.empty()
    subtitles = []
    current_time_sec = 0.0
    natural_pause = AudioSegment.silent(duration=150)

    for idx, chunk_audio in audio_results:
        if not chunk_audio:
            continue
            
        temp_file = f"temp_line_{idx}.mp3"
        with open(temp_file, "wb") as f:
            f.write(chunk_audio)

        try:
            segment = AudioSegment.from_mp3(temp_file)
            nonsilent_ranges = detect_nonsilent(segment, min_silence_len=50, silence_thresh=-50)
            if nonsilent_ranges:
                start_trim = nonsilent_ranges[0][0]
                end_trim = nonsilent_ranges[-1][1]
                segment = segment[start_trim:end_trim]

            segment = segment + natural_pause
            duration_sec = len(segment) / 1000.0

            if duration_sec > 0:
                end_time = current_time_sec + duration_sec
                subtitles.append({
                    "start": current_time_sec,
                    "end": end_time,
                    "text": sentences[idx]
                })
                current_time_sec = end_time
                combined_audio += segment
                
        except Exception as e:
            print(f"Error processing line {idx}: {e}")
            
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    progress(0.9, desc="💾 ဖိုင်များကို သိမ်းဆည်းနေပါသည်...")

    if len(combined_audio) == 0:
        return None, None, None, gr.update(visible=False)

    combined_audio.export(output_mp3, format="mp3")

    with open(output_srt, "w", encoding="utf-8-sig") as f:
        for i, sub in enumerate(subtitles, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(sub['start'])} --> {format_srt_time(sub['end'])}\n")
            f.write(sub["text"].strip())
            f.write("\n\n")

    progress(1.0, desc="✅ အားလုံး ပြီးစီးပါပြီ!")
    return output_mp3, output_mp3, output_srt, gr.update(visible=False)

def tts_wrapper(text, rules_text, filename, s1_voice, s2_voice, s3_voice, style, srt_type, tone, speed, volume, progress=gr.Progress()):
    return asyncio.run(tts_wrapper_async(text, rules_text, filename, s1_voice, s2_voice, s3_voice, style, srt_type, tone, speed, volume, progress))

async def tts_wrapper_async(text, rules_text, filename, s1_voice, s2_voice, s3_voice, style, srt_type, tone, speed, volume, progress=gr.Progress()):
    return await process_voice_generation(text, surveyed_text=rules_text, filename=filename, s1_voice=s1_voice, s2_voice=s2_voice, s3_voice=s3_voice, style=style, srt_type=srt_type, tone=tone, speed=speed, volume=volume, progress=progress)

custom_css = """
.large-btn { font-size: 24px !important; font-weight: bold !important; padding: 15px !important; margin-bottom: 15px !important; }
.text-link-box { text-align: center; margin-bottom: 20px; padding: 10px; background-color: #1E293B; border-radius: 8px; }
.text-link-box p { font-size: 20px !important; margin: 5px 0 !important; font-weight: 500; }
.text-link-box a { color: #38BDF8 !important; text-decoration: underline !important; font-weight: bold !important; font-size: 24px !important; }
"""

with gr.Blocks(title="Myanmar Audio Studio", css=custom_css) as demo:
    gr.Markdown("<h1 style='text-align: center; color: #4F46E5;'>🎙️ Myanmar Audio & SRT Studio</h1>")
    
    with gr.Column():
        free_status_btn = gr.Button("🆓 TTS and SRT Free Version", variant="primary", interactive=False, elem_classes=["large-btn"])
        
        gr.HTML(
            "<div class='text-link-box'>"
            "<p style='color: #FFFFFF;'>💬 User များစကားပြောရန် Group</p>"
            "<p><a href='https://t.me/paingttsandsrt' target='_blank'>@PAINGTTSANDSRT</a></p>"
            "</div>"
        )
    
    gr.Markdown("<hr style='margin: 20px 0;'>")

    with gr.Group() as tts_content:
        engine = gr.Radio(choices=["သီဟနီလာတို့အစု", "Gemini API"], label="🤖 TTS Engine", value="သီဟနီလာတို့အစု")
        api_key = gr.Textbox(label="🔑 Gemini API Key", placeholder="Gemini API သုံးမှသာ ထည့်ရန်...", interactive=True)
        
        with gr.Accordion("🔧 အသံထွက် ပြင်ဆင်ရန် (Pronunciation Rules)", open=False):
            rules = gr.TextArea(value="", placeholder="ဥပမာ - စာသား = အသံထွက်", lines=4, show_label=False)
            
        file_name = gr.Textbox(label="💾 သိမ်းဆည်းမည့် ဖိုင်အမည်", value="Myanmar_TTS")
        voice_choices = ["သီဟ (🇲🇲 - ကျား)", "နီလာ (🇲🇲 - မ)", "စမူပိုင်ကြီး (🇲🇲 - ကျား)"]
        
        with gr.Row():
            s1_voice = gr.Dropdown(voice_choices, label="🎙️ [S1] အသံ", value="သီဟ (🇲🇲 - ကျား)")
            s2_voice = gr.Dropdown(voice_choices, label="🎙️ [S2] အသံ", value="နီလာ (🇲🇲 - မ)")
            s3_voice = gr.Dropdown(voice_choices, label="🎙️ [S3] အသံ", value="စမူပိုင်ကြီး (🇲🇲 - ကျား)")
            
        with gr.Row():
            style = gr.Dropdown(["Normal (ပုံမှန်)", "Whispering", "Excited"], label="🎭 အသံစတိုင်လ်", value="Normal (ပုံမှန်)")
            srt_type = gr.Radio(["TikTok", "YouTube"], label="စာတန်းထိုး အမျိုးအစား", value="TikTok")
            
        with gr.Accordion("⚙️ အဆင့်မြင့် ဆက်တင်များ", open=False):
            tone = gr.Slider(minimum=-50, maximum=50, value=0, step=1, label="Tone")
            speed = gr.Slider(minimum=-50, maximum=50, value=0, step=1, label="Speed")
            volume = gr.Slider(minimum=0, maximum=100, value=50, step=1, label="Volume (+%)")
            
        input_text = gr.Textbox(label="စာသား", placeholder="မင်္ဂလာပါ။", lines=4)
        generate_btn = gr.Button("🚀 အသံဖိုင် ဖန်တီးမည် (Generate)", variant="primary")
        tg_connect_btn = gr.Button("🔥 VIP ဝယ်ယူရန် Telegram သို့ ဆက်သွယ်မည်", variant="stop", visible=False)
        
        output_audio = gr.Audio(label="🎧 ထွက်လာသော အသံဖိုင်", type="filepath")
        output_mp3_file = gr.File(label="💾 MP3 ဒေါင်းလုဒ်")
        output_srt_file = gr.File(label="📝 SRT ဒေါင်းလုဒ်")

        generate_btn.click(
            fn=tts_wrapper, 
            inputs=[input_text, rules, file_name, s1_voice, s2_voice, s3_voice, style, srt_type, tone, speed, volume], 
            outputs=[output_audio, output_mp3_file, output_srt_file, tg_connect_btn]
        )
        
        with gr.Accordion("👑 Admin Control Panel", open=False):
            with gr.Row():
                adm_pass = gr.Textbox(label="🔐 Admin Security Password", type="password")
                u_pass_input = gr.Textbox(label="🔑 User VIP Password")
                days_input = gr.Slider(minimum=1, maximum=365, value=30, step=1, label="⏳ ရက်ပေါင်း")
            register_btn = gr.Button("✨ VIP သတ်မှတ်မည်", variant="secondary")
            admin_output = gr.Textbox(label="📢 ရလဒ်")
            status_btn = gr.Button("📋 VIP စာရင်းကြည့်မည်")
            status_output = gr.TextArea(label="စာရင်းများ", lines=5)
            register_btn.click(fn=register_or_renew_vip, inputs=[adm_pass, u_pass_input, days_input], outputs=admin_output)
            status_btn.click(fn=check_vip_status_ui, inputs=None, outputs=status_output)

demo.launch()
                  
