import json
import socket
import time
from machine import ADC, Pin
import network

# センサーの接続ピン設定 (GP26に修正)
sensor = ADC(Pin(26))
Wifi_Led = Pin(5, Pin.OUT)
Count_Led = Pin(9, Pin.OUT)
Reset_Btn = Pin(0, Pin.IN, Pin.PULL_UP)

# 物体検出のしきい値（今回は「20cm以内に入ったら」という設定にしてみます）
# 好みに合わせて変更してください（例: 30cm 以内なら 30）
THRESHOLD_CM = 15

# Wi-Fiの接続情報（ご自身の環境に合わせて書き換えてください）
SSID = "BUFFALO-G"
PASSWORD = "123456789ab0"

# WebSocketサーバーの設定
WS_HOST = "192.168.3.138"
WS_PORT = 8765

# Wi-Fi接続用の変数（グローバルで管理）
wlan = None

# -- WebSocketデータ送信関数 --
def send_ws_message(host, port, payload):
    """シンプルなWebSocketハンドシェイクを行い、JSONデータを送信する関数"""
    try:
        # ソケット作成と接続
        addr = socket.getaddrinfo(host, port)[0][-1]
        s = socket.socket()
        s.settimeout(3.0)  # タイムアウト設定
        s.connect(addr)

        # WebSocketのハンドシェイク要求リクエスト
        # (最低限必要なヘッダーのみ)
        handshake = (
            "GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.send(handshake.encode())

        # サーバーからのレスポンスを受信（ヘッダーの読み飛ばし）
        # ※実際の運用では検証するのが望ましいですが、軽量化のためスキップ
        response = s.recv(1024)

        # JSONデータを文字列に変換してバイト配列化
        msg = json.dumps(payload).encode("utf-8")
        msg_len = len(msg)

        # WebSocketフレームの作成 (Text frame, Masked from client)
        # MicroPython(クライアント)から送信する場合、マスク処理(Masking)が必須です
        frame = bytearray()
        frame.append(0x81)  # FIN=1, Opcode=1 (Text)

        # マスクキー (固定の4バイト、何でも良い)
        mask_key = b"\x11\x22\x33\x44"

        if msg_len <= 125:
            frame.append(msg_len | 0x80)  # Maskフラグ(0x80)を立てる
        elif msg_len <= 65535:
            frame.append(126 | 0x80)
            frame.append((msg_len >> 8) & 0xFF)
            frame.append(msg_len & 0xFF)
        else:
            # 巨大なデータは扱わない前提
            s.close()
            return False

        frame.extend(mask_key)

        # データのマスク処理（XOR演算）
        masked_msg = bytearray(msg_len)
        for i in range(msg_len):
            masked_msg[i] = msg[i] ^ mask_key[i % 4]

        frame.extend(masked_msg)

        # フレームの送信
        s.send(frame)
        print(f"WebSocket送信成功: {payload}")

        # 接続を閉じる
        s.close()
        return True

    except Exception as e:
        print(f"WebSocket送信エラー: {e}")
        return False

#-- 赤外線センサーから距離を取得する関数 --    
def get_distance():
    # 複数回サンプリングして平均を取り、ノイズを軽減する
    total = 0
    samples = 10
    for _ in range(samples):
        total += sensor.read_u16()
        time.sleep_ms(5)
    
    avg_reading = total / samples
    voltage = (avg_reading * 3.3) / 65535
    
    if voltage < 0.4:
        return float('inf')
        
    distance_cm = 26.985 / (voltage - 0.05)
    
    if distance_cm > 80:
        return 80.0
    elif distance_cm < 10:
        return 10.0
        
    return distance_cm
    
# -- 赤外線センサーの距離測定と物体検出のメインループ --
def IrCenceer():

    global wlan

    # カウント変数と状態管理フラグ
    count = 0
    object_detected = False

    # 起動時のタイムスタンプを記録
    start_time = time.ticks_ms()

    while True:

        # 現在のミリ秒を取得し、起動時からの差分（経過ミリ秒）を計算
        elapsed_ms = time.ticks_diff(time.ticks_ms(), start_time)
        elapsed_sec = elapsed_ms / 1000.0

        distance_cm = get_distance()  # より安定した距離値を取得するための関数呼び出し

        #print(f"距離: {distance_cm:.1f} cm (センサー値: {analog_value})")

        print(f"{elapsed_sec:7.2f}s - 距離: {distance_cm:.1f} cm")
        
        # しきい値より「小さくなった（＝近づいた）」場合
        # ※距離なので、THRESHOLD_CMより数値が小さくなったら検出になります
        if distance_cm < THRESHOLD_CM:
            if not object_detected:
                count += 1
                print(f"【検出】物体が {THRESHOLD_CM}cm 以内を通過！ カウント: {count}")
                object_detected = True  # フラグをTrueにして連続カウントを防ぐ
                Count_Led.value(1)

                # --- WebSocketでJSONデータを送信 ---
                if wlan is not None and wlan.isconnected():
                    send_data = {"type": "counter", "value": 1}
                    send_ws_message(WS_HOST, WS_PORT, send_data)
                else:
                    print("Wi-Fi未接続のため、データ送信をスキップしました。")

        # しきい値を上回った（物体が遠ざかった）場合
        else:
            if object_detected:
                object_detected = False
                Count_Led.value(0)
                print("物体が離れました。")

        # Wi-Fi関連
        if wlan is not None and not wlan.isconnected():
            print("Wi-Fi接続が切れました。再接続を試みます...")
            connect_wifi()
        
        # トグルスイッチのONを検知
        if Reset_Btn.value() == 0:  # ボタンが押されたとき（アクティブロー）

            # --- WebSocketでJSONデータを送信 ---
            if wlan is not None and wlan.isconnected():
                send_data = {"type": "reset"}
                send_ws_message(WS_HOST, WS_PORT, send_data)
                print("リセットボタンが押されました。カウントをリセットします。")
            else:
                print("Wi-Fi未接続のため、データ送信をスキップしました。")
            count = 0
            Count_Led.value(0)
            time.sleep(0.5)  # ボタンのチャタリング防止のため少し待つ

        time.sleep(0.05)

# -- Wi-Fi接続関数 --
def connect_wifi():

    global wlan

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"{SSID} に接続中...")
        wlan.connect(SSID, PASSWORD)
        
        # タイムアウト時間を秒単位で設定（5分 ＝ 300秒）
        TIMEOUT_SECONDS = 60 * 5
        
        # 【変更点】ループ開始前の「現在の時間（ミリ秒）」を記録
        start_time_ms = time.ticks_ms()
        
        led_status = 0
        last_toggle_time = start_time_ms # LEDの点滅タイミングを計るための変数
        last_msg_time = start_time_ms # 接続待ちメッセージの表示タイミングを計るための変数
        
        while not wlan.isconnected():
            # 【変更点】開始からの経過秒数を計算する
            current_time_ms = time.ticks_ms()
            elapsed_seconds = time.ticks_diff(current_time_ms, start_time_ms) // 1000
            
            # 残り秒数を算出
            remaining_seconds = TIMEOUT_SECONDS - elapsed_seconds
            
            # 指定時間を超えたらループを終了（タイムアウト）
            if remaining_seconds <= 0:
                break
                
            # --- 1秒ごとに情報を表示 ＆ LEDを反転 ---
            # 前回の反転から1000ミリ秒（1秒）以上経っていたら処理
            if time.ticks_diff(current_time_ms, last_msg_time) >= 1000:
                print(f"... 接続待ち (実時間での残り {remaining_seconds} 秒)")
                last_msg_time = current_time_ms

            # --- 0.3秒ごとにLEDを反転 ---
            # 前回の反転から300ミリ秒（0.3秒）以上経っていたら処理
            if time.ticks_diff(current_time_ms, last_toggle_time) >= 300:
                # LEDの点滅
                led_status = 1 - led_status
                Wifi_Led.value(led_status)
                last_toggle_time = current_time_ms
                
            time.sleep(0.01)
            
    if wlan.isconnected():
        print("--- Wi-Fi接続成功！ ---")
        Wifi_Led.value(1) # 常時点灯
        print("ネットワーク情報:", wlan.ifconfig())
        return True
    else:
        print("--- 接続失敗（タイムアウト） ---")
        Wifi_Led.value(0) # 消灯
        return False
    
# Wi-Fiに接続
if not connect_wifi():
    print("Wi-Fi接続に失敗しました。")
    exit()

# 赤外線センサーの実行
IrCenceer()
