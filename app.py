import streamlit as st
import requests
import time
import base64
import random
from PIL import Image
import io
import os

st.set_page_config(page_title="自作 AI Video Generator", layout="centered")

# ---------------------------------------------------------
# 0. 履歴フォルダの管理＆24時間自動消去機能
# ---------------------------------------------------------
OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def cleanup_old_videos(max_age_seconds=86400):
    """24時間（86400秒）以上古い動画ファイルを自動削除する"""
    now = time.time()
    for filename in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, filename)
        if os.path.isfile(file_path) and filename.endswith(".mp4"):
            file_age = now - os.path.getmtime(file_path)
            if file_age > max_age_seconds:
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"古いファイルの削除エラー ({filename}): {e}")

cleanup_old_videos()

# ---------------------------------------------------------
# 1. セキュリティ設定（ログイン状態の保持）
# ---------------------------------------------------------
def check_password():
    if "APP_PASSWORD" not in st.secrets:
        return True

    if st.session_state.get("authenticated", False):
        return True

    st.title("🔒 パスワード認証")
    user_password = st.text_input("アプリのアクセスパスワードを入力してください", type="password")
    
    if st.button("ログイン", type="primary"):
        if user_password == st.secrets["APP_PASSWORD"]:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    return False

if not check_password():
    st.stop()

# ---------------------------------------------------------
# 2. 認証・設定値の自動読み込み
# ---------------------------------------------------------
st.title("🎬 自作 AI Video Generator (全モデル対応版)")

default_api_key = st.secrets.get("RUNPOD_API_KEY", "")
endpoints_dict = dict(st.secrets.get("ENDPOINTS", {}))
endpoint_options = list(endpoints_dict.keys()) + ["手動入力 / カスタムID"]

# ---------------------------------------------------------
# 3. サイドバー設定エリア
# ---------------------------------------------------------
st.sidebar.header("🔑 RunPod 認証設定")
api_key = st.sidebar.text_input("RunPod API Key", value=default_api_key, type="password")

selected_endpoint_label = st.sidebar.selectbox(
    "Endpoint ID 選択",
    options=endpoint_options,
    index=0 if endpoint_options else 0
)

if selected_endpoint_label == "手動入力 / カスタムID":
    endpoint_id = st.sidebar.text_input("Endpoint IDを直接入力")
else:
    endpoint_id = endpoints_dict.get(selected_endpoint_label, "")
    st.sidebar.caption(f"選択中ID: `{endpoint_id}`")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ 動画生成設定")

# 秒数選択メニュー
seconds = st.sidebar.selectbox(
    "動画の長さ (秒)",
    options=[5, 7, 10, 15],
    index=0
)

# フレームレート (FPS) 選択メニュー（RunPod側の制約 10〜20 に合わせる）
fps = st.sidebar.selectbox(
    "フレームレート (FPS)",
    options=[10, 12, 15, 16, 20],
    index=3
)

# 解像度設定モード
resolution_mode = st.sidebar.radio(
    "解像度モード",
    options=["画像のアスペクト比に自動追従", "手動指定 (横長基準)"],
    index=0
)

if resolution_mode == "手動指定 (横長基準)":
    resolution_option = st.sidebar.selectbox(
        "基準解像度 (幅 x 高さ)",
        options=["Minimax推奨 (768x512)", "高 (1024x576)", "中 (704x480)"],
        index=0
    )
    if resolution_option == "高 (1024x576)":
        base_w, base_h = 1024, 576
    elif resolution_option == "中 (704x480)":
        base_w, base_h = 704, 480
    else:
        base_w, base_h = 768, 512
else:
    base_w, base_h = 768, 512

# ---------------------------------------------------------
# 新機能: 🎨 LoRA 設定メニュー
# ---------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("🎨 LoRA 設定")

# 使用したいLoRAファイル名を定義（RunPod上のモデル名と一致させます）
lora_options = [
    "なし",
    "anime_style.safetensors",
    "cinematic_lighting.safetensors",
    "camera_motion_zoom.safetensors",
    "Wan 2.2 Close-Up Facial Cumshots",
    "手動入力 / カスタムファイル名"
]

selected_lora = st.sidebar.selectbox("使用する LoRA 選択", options=lora_options, index=0)

if selected_lora == "手動入力 / カスタムファイル名":
    lora_name = st.sidebar.text_input("LoRA ファイル名 (例: my_lora.safetensors)")
elif selected_lora != "なし":
    lora_name = selected_lora
else:
    lora_name = ""

# LoRA強度の設定スライダー
lora_weight = st.sidebar.slider(
    "LoRA 適用強度 (Weight)",
    min_value=0.0,
    max_value=1.5,
    value=0.8,
    step=0.05,
    disabled=(selected_lora == "なし")
)

# シード値の設定
st.sidebar.markdown("---")
random_seed = st.sidebar.checkbox("シード値をランダム生成する", value=True)
if random_seed:
    seed_value = random.randint(0, 4294967295)
else:
    seed_value = st.sidebar.number_input("シード値 (0 ~ 4294967295)", min_value=0, max_value=4294967295, value=42, step=1)

# ログアウトボタン
if st.sidebar.button("🔒 ログアウト"):
    st.session_state["authenticated"] = False
    st.rerun()

# ---------------------------------------------------------
# 4. メイン画面エリア（入力・プレビュー表示）
# ---------------------------------------------------------
uploaded_file = st.file_uploader("ベースとなる画像を選択してください (I2V用)", type=["png", "jpg", "jpeg"])

if uploaded_file:
    image_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.caption("📷 選択中の画像プレビュー:")
        st.image(image_bytes, width=180)

prompt = st.text_area("プロンプト（動作の指示文）を入力してください", "A cinematic camera panning, high quality, 4k")

# ---------------------------------------------------------
# 5. 動画生成の実行処理
# ---------------------------------------------------------
if st.button("動画を生成する", type="primary"):
    if not api_key or not endpoint_id:
        st.error("API KeyとEndpoint IDを設定してください。")
    elif not uploaded_file:
        st.error("I2V生成を行うには、元となる画像をアップロードしてください。")
    else:
        # 画像読み込み・縦横補正
        image_bytes = uploaded_file.read()
        pil_img = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = pil_img.size

        if resolution_mode == "画像のアスペクト比に自動追従":
            if img_h > img_w:
                width, height = base_h, base_w
            else:
                width, height = base_w, base_h
        else:
            width, height = base_w, base_h

        width = (width // 32) * 32
        height = (height // 32) * 32

        st.info(f"📐 送信解像度: 横 {width}px × 縦 {height}px | 設定: {seconds}秒 ({fps} FPS)" + (f" | 🎨 LoRA: {lora_name} ({lora_weight})" if lora_name else ""))

        base64_str = base64.b64encode(image_bytes).decode('utf-8')
        data_uri = f"data:image/png;base64,{base64_str}"
        mime_type = uploaded_file.type or "image/png"
        
        run_url = f"https://api.runpod.ai/v2/{endpoint_id}/run"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        strict_media_obj = {
            "base64": base64_str,
            "mime": mime_type,
            "name": uploaded_file.name or "input_image.png",
            "type": "image"
        }
        
        generic_source_obj = {
            "image": data_uri,
            "base64": base64_str,
            "data": base64_str,
            "name": uploaded_file.name or "input_image.png"
        }
        
        frames = seconds * fps
        
        # 基本の input 辞書構築
        input_data = {
            "prompt": prompt,
            "mode": "i2v",
            "seed": int(seed_value),
            "width": int(width),
            "height": int(height),
            "seconds": seconds,
            "duration": seconds,
            "frames": frames,
            "fps": fps,
            "refs": [strict_media_obj],
            "references": [strict_media_obj],
            "source": generic_source_obj,
            "image": data_uri,
            "image_url": data_uri
        }
        
        # LoRA が指定されている場合にパラメータを追加
        if lora_name:
            input_data["lora_name"] = lora_name
            input_data["lora_weight"] = float(lora_weight)
            input_data["lora_scale"] = float(lora_weight)
            input_data["loras"] = [{"name": lora_name, "weight": float(lora_weight)}]
        
        payload = {"input": input_data}
        
        try:
            with st.spinner("RunPodにリクエスト送信中..."):
                res = requests.post(run_url, json=payload, headers=headers)
                res_data = res.json()
            
            if "id" in res_data:
                job_id = res_data["id"]
                st.info(f"ジョブを開始しました (ID: {job_id})")
                
                status_url = f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}"
                status_placeholder = st.empty()
                
                while True:
                    status_res = requests.get(status_url, headers=headers)
                    status_data = status_res.json()
                    status = status_data.get("status")
                    
                    status_placeholder.text(f"ステータス: {status} (動画生成中...)")
                    
                    if status == "COMPLETED":
                        status_placeholder.empty()
                        st.success("✨ 動画の生成が完了しました！")
                        
                        output = status_data.get("output") or {}
                        video_bytes = None
                        
                        if isinstance(output, dict) and "video_base64" in output:
                            video_bytes = base64.b64decode(output["video_base64"])
                        else:
                            video_url = None
                            if isinstance(output, list) and len(output) > 0:
                                video_url = output[0] if isinstance(output[0], str) else output[0].get("url")
                            elif isinstance(output, dict):
                                video_url = output.get("video") or output.get("message") or output.get("result") or output.get("url")
                            elif isinstance(output, str):
                                video_url = output

                            if video_url and str(video_url).startswith("http"):
                                with st.spinner("動画ファイルをダウンロード中..."):
                                    video_bytes = requests.get(video_url).content

                        if video_bytes:
                            saved_filename = f"gen_{int(time.time())}_{job_id[:8]}.mp4"
                            save_path = os.path.join(OUTPUT_DIR, saved_filename)
                            
                            with open(save_path, "wb") as f:
                                f.write(video_bytes)
                                
                            st.rerun()
                        else:
                            st.warning("生成は完了しましたが、動画データの読み込みに失敗しました。")
                            st.json(output)
                        break
                        
                    elif status in ["FAILED", "CANCELLED"]:
                        status_placeholder.empty()
                        st.error("動画生成処理が失敗しました。")
                        st.json(status_data)
                        break
                        
                    time.sleep(5)
            else:
                st.error("RunPodへのリクエスト送信に失敗しました。")
                st.json(res_data)
                
        except Exception as e:
            st.error(f"通信エラーが発生しました: {e}")

# ---------------------------------------------------------
# 6. 過去の生成履歴表示ギャラリー（24時間以内の保存動画）
# ---------------------------------------------------------
st.markdown("---")
st.subheader("🎞️ 過去の生成履歴 (24時間以内)")

saved_files = []
if os.path.exists(OUTPUT_DIR):
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".mp4"):
            f_path = os.path.join(OUTPUT_DIR, f)
            mtime = os.path.getmtime(f_path)
            saved_files.append((f, f_path, mtime))

saved_files.sort(key=lambda x: x[2], reverse=True)

if saved_files:
    for idx, (f_name, f_path, mtime) in enumerate(saved_files):
        created_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        
        with st.expander(f"🎬 動画 #{idx + 1} - 生成日時: {created_time_str}", expanded=(idx == 0)):
            st.video(f_path)
            
            with open(f_path, "rb") as file_data:
                st.download_button(
                    label=f"💾 この動画（{f_name}）を保存",
                    data=file_data.read(),
                    file_name=f_name,
                    mime="video/mp4",
                    key=f"dl_btn_{f_name}"
                )
else:
    st.info("過去24時間以内に生成された動画はありません。")