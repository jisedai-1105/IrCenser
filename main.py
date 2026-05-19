import time
from machine import ADC, Pin
import network

# センサーの接続ピン設定 (GP26に修正)
sensor = ADC(Pin(26))
Wifi_Led = Pin(28, Pin.OUT)
Count_Led = Pin(1, Pin.OUT)
Reset_Btn = Pin(0, Pin.IN, Pin.PULL_UP)

# 物体検出のしきい値（今回は「20cm以内に入ったら」という設定にしてみます）
# 好みに合わせて変更してください（例: 30cm 以内なら 30）
THRESHOLD_CM = 10

# Wi-Fiの接続情報（ご自身の環境に合わせて書き換えてください）
SSID = "BUFFALO-G"
PASSWORD = "123456789ab0"

# Wi-Fi接続用の変数（グローバルで管理）
wlan = None

# -- 赤外線センサーの距離測定と物体検出のメインループ --
def IrCenceer():

    global wlan

    # カウント変数と状態管理フラグ
    count = 0
    object_detected = False

    while True:
        analog_value = sensor.read_u16()
        voltage = analog_value * 3.3 / 65535
        
        # 3. 電圧から距離(cm)に換算する近似式
        # ※電圧が極端に低い(0.3V以下＝何も無い)ときのゼロ除算エラーを防ぐ処理付き
        if voltage > 0.3:
            # 2Y0A21用の定番の換算式です
            distance_cm = 13 / (voltage - 0.1)
        else:
            distance_cm = 80.0 # 反応がない場合は最大距離（約80cm）とする

        #print(f"距離: {distance_cm:.1f} cm (センサー値: {analog_value})")
        
        # しきい値より「小さくなった（＝近づいた）」場合
        # ※距離なので、THRESHOLD_CMより数値が小さくなったら検出になります
        if distance_cm < THRESHOLD_CM:
            if not object_detected:
                count += 1
                print(f"【検出】物体が {THRESHOLD_CM}cm 以内を通過！ カウント: {count}")
                object_detected = True  # フラグをTrueにして連続カウントを防ぐ
                Count_Led.value(1)

                
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
            print("リセットボタンが押されました。カウントをリセットします。")
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
