import json
import socket
import time
from machine import ADC, Pin
import network

# センサーの接続ピン設定 (GP26に修正)
sensor = ADC(Pin(26))
Wifi_Led = Pin(5, Pin.OUT)
Count_Led = Pin(9, Pin.OUT)
Error_Led = Pin(13, Pin.OUT)
Reset_Btn = Pin(0, Pin.IN, Pin.PULL_UP)
DistReset_Btn = Pin(22, Pin.IN, Pin.PULL_UP)

# 物体検出のしきい値（今回は「20cm以内に入ったら」という設定にしてみます）
# 好みに合わせて変更してください（例: 30cm 以内なら 30）
THRESHOLD_CM = 15

##################################################
# 3F
##################################################
# Wi-Fiの接続情報（ご自身の環境に合わせて書き換えてください）
SSID = "BUFFALO-G"
PASSWORD = "123456789ab0"

# WebSocketサーバーの設定
WS_HOST = "192.168.3.139"
WS_PORT = 8765

##################################################
# EP
##################################################
# Wi-Fiの接続情報（ご自身の環境に合わせて書き換えてください）
#SSID = "687AA0_G"
#PASSWORD = "hGYk9ZvG"

# WebSocketサーバーの設定
#WS_HOST = "192.1.2.62"
#WS_PORT = 8765


# カウンターの識別番号（複数台設置する場合などに区別するため）
LINE_NO = 1

# データ送信の間隔（秒）
SEND_INTERVAL_SEC = 0.5

# 一回当たりのカウント数
VALUE = 1

# Wi-Fi接続用の変数（グローバルで管理）
wlan = None

# ソケット
MySocket = socket.socket()


# 距離リセットの設定パラメータ（ミリ秒）
DOUBLE_CLICK_TIME = 300  # ダブルクリックを待つ時間
DEBOUNCE_TIME = 50       # チャタリング防止

# 距離リセットの状態管理用
last_press_time = 0
click_count = 0
waiting_for_double = False

# -- ソケットを開く関数 --
def socket_open():

    global MySocket
    count = 0

    while True:
        try:

            MySocket = socket.socket()
            addr = socket.getaddrinfo(WS_HOST, WS_PORT)[0][-1]
            MySocket.settimeout(3.0)  # タイムアウト設定
            MySocket.connect(addr)

            # WebSocketのハンドシェイク要求リクエスト
            # (最低限必要なヘッダーのみ)
            handshake = (
                "GET / HTTP/1.1\r\n"
                f"Host: {WS_HOST}:{WS_PORT}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            MySocket.send(handshake.encode())

            # サーバーからのレスポンスを受信（ヘッダーの読み飛ばし）
            # ※実際の運用では検証するのが望ましいですが、軽量化のためスキップ
            response = MySocket.recv(1024)

            Error_Led.value(0)
            break  

        except Exception as e:
            Led_Websocket_Error()
            count += 1
            if count >= 10:
                break
            print(f"WebSocket 接続エラー: {e}")
            time.sleep(1) 

# -- ソケットを閉じる関数 --
def socket_close():
    global MySocket
    try:
        MySocket.close()
    except Exception as e:
        pass

# -- WebSocketデータ送信関数 --
def send_ws_message(host, port, payload):
    
    global MySocket

    """シンプルなWebSocketハンドシェイクを行い、JSONデータを送信する関数"""
    try:

        socket_open()  

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
            return False

        frame.extend(mask_key)

        # データのマスク処理（XOR演算）
        masked_msg = bytearray(msg_len)
        for i in range(msg_len):
            masked_msg[i] = msg[i] ^ mask_key[i % 4]

        frame.extend(masked_msg)

        # フレームの送信
        MySocket.send(frame)
        print(f"WebSocket送信成功: {payload}")

        socket_close() 

        return True

    except Exception as e:
        print(f"WebSocket送信エラー: {e}")
        Led_Websocket_Error()
        return False

# -- WebSocket送信エラー時のLED点滅関数 --
def Led_Websocket_Error():
    Error_Led.value(1)
    time.sleep(0.2)
    Error_Led.value(0)
    time.sleep(0.2)
    Error_Led.value(1)
    time.sleep(0.2)
    Error_Led.value(0)

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

# -- WebSocket送信エラー時のLED点滅関数 --
def Led_Rest_ON():
    Error_Led.value(1)
    Wifi_Led.value(1)
    Count_Led.value(1)
    time.sleep(2)
    Error_Led.value(0)
    Wifi_Led.value(0)
    Count_Led.value(0)

# -- 赤外線センサーの距離測定と物体検出のメインループ --
def IrCenceer():

    global wlan, click_count, last_press_time, waiting_for_double

    # カウント変数と状態管理フラグ
    count = 0
    object_detected = False

    # ソケットを開く
    #socket_open()  

    # 起動時のタイムスタンプを記録
    start_time = time.ticks_ms()
    bef_sec = 0
    exe_sec = 0

    while True:

        current_time = time.ticks_ms()

        # 現在のミリ秒を取得し、起動時からの差分（経過ミリ秒）を計算
        elapsed_ms = time.ticks_diff(time.ticks_ms(), start_time)
        elapsed_sec = elapsed_ms / 1000.0
        exe_sec = elapsed_sec - bef_sec 

        distance_cm = get_distance()  # より安定した距離値を取得するための関数呼び出し

        Count_Led.value(0)

        # --- WebSocketでJSONデータを送信 ---
        if wlan is not None and wlan.isconnected():
            if bef_sec == 0 or exe_sec >= SEND_INTERVAL_SEC:

                #print(f"WS_HOST: {WS_HOST} / WS_PORT: {WS_PORT} / LineNo: {LINE_NO} / 距離: {distance_cm:.2f} cm")

                send_data = {"type": "dist","no": LINE_NO,"dist": distance_cm, "sec": SEND_INTERVAL_SEC}
                IsSend = send_ws_message(WS_HOST, WS_PORT, send_data)
                bef_sec = elapsed_sec
                if IsSend == True:
                    Count_Led.value(1)

        else:
            print("Wi-Fi未接続のため、データ送信をスキップしました。")

        # トグルスイッチのONを検知
        if Reset_Btn.value() == 0:  # ボタンが押されたとき（アクティブロー）

            print("リセットボタンが押されました。")
            Led_Rest_ON()

            #time.sleep(0.5)  # ボタンのチャタリング防止のため少し待つ
            #if wlan is not None and not wlan.isconnected():
            #    connect_wifi()
            connect_wifi()

        # 距離のリセットボタンのシングルクリック
        if DistReset_Btn.value() == 0 :
            if time.ticks_diff(current_time, last_press_time) > DEBOUNCE_TIME:
                click_count += 1
                last_press_time = current_time
                waiting_for_double = True

            # 2回押されたらその時点でダブルクリック確定
            if click_count == 2:
                print("★ダブルクリック検知")

                send_data = {"type": "RstDistRst" , "no": LINE_NO , "sec": SEND_INTERVAL_SEC}
                IsSend = send_ws_message(WS_HOST, WS_PORT, send_data)
                bef_sec = elapsed_sec
                if IsSend == True:
                    Count_Led.value(1)

                click_count = 0
                waiting_for_double = False
                
        # ボタンが離されるまで待機（長押し対策）
        while DistReset_Btn.value() == 0:
            time.sleep_ms(10)

        # 2. ボタンが押された後、2回目が来ずに制限時間を過ぎた場合の処理
        if waiting_for_double and click_count == 1:
            if time.ticks_diff(current_time, last_press_time) > DOUBLE_CLICK_TIME:
                print("〇シングルクリック検知")
                # 【ここにシングルクリック時の処理を書く】

                send_data = {"type": "RstDist" , "no": LINE_NO , "dist": distance_cm , "sec": SEND_INTERVAL_SEC}
                IsSend = send_ws_message(WS_HOST, WS_PORT, send_data)
                bef_sec = elapsed_sec
                if IsSend == True:
                    Count_Led.value(1)

                click_count = 0
                waiting_for_double = False

        # Wi-Fi関連
        if wlan is not None and not wlan.isconnected():
            Error_Led.value(1)
            print("Wi-Fi接続が切れました。再接続を試みます...")
            connect_wifi()

        if wlan is not None and not wlan.isconnected():
            pass
        else:
            Error_Led.value(0)

        time.sleep(0.05)

    # ソケットを閉じる
    socket_close()  

# -- Wi-Fi接続関数 --
def connect_wifi():

    global wlan

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"{SSID} に接続中...")
        wlan.connect(SSID, PASSWORD)
        
        # タイムアウト時間を秒単位で設定
        TIMEOUT_SECONDS = 60 * 3
        
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

try :
    # Wi-Fiに接続
    if not connect_wifi():
        print("Wi-Fi接続に失敗しました。")
        exit()
    # 赤外線センサーの実行
    IrCenceer()
except KeyboardInterrupt:    
    print("プログラムを終了します。")
finally:
    Wifi_Led.value(0)
    Count_Led.value(0)
    Error_Led.value(0)
    socket_close()
