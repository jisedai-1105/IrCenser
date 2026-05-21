import machine
import time

# ADC0 (GP26) を初期化
adc = machine.ADC(26)

# 起動時のタイムスタンプを記録
start_time = time.ticks_ms()

def get_distance():
    # 複数回サンプリングして平均を取り、ノイズを軽減する
    total = 0
    samples = 10
    for _ in range(samples):
        total += adc.read_u16()
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

# メインループ
print("シャープ測距センサー GP2Y0A21 測定開始...")
while True:
    # 現在のミリ秒を取得し、起動時からの差分（経過ミリ秒）を計算
    elapsed_ms = time.ticks_diff(time.ticks_ms(), start_time)
    
    # ミリ秒を「秒」に変換 (必要なら少数点以下も残す)
    elapsed_sec = elapsed_ms / 1000.0
    
    dist = get_distance()
    
    # 経過時間を「[ 12.34s ]」のような形式で頭に付けてプリント
    if dist == float('inf'):
        print(f"[{elapsed_sec:7.2f}s] 範囲外（目標物が遠すぎるか、近すぎます）")
    else:
        print(f"[{elapsed_sec:7.2f}s] 距離: {dist:.1f} cm")
        
    time.sleep(0.5)