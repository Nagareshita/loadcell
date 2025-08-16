// --- 4ch ロードセル対応版 ---
#include "HX711.h"

// --- 4ch分のピン定義 ---
const int DOUT_PINS[4] = {2, 4, 6, 8};   // HX711 DAT pins
const int SCK_PINS[4]  = {3, 5, 7, 9};   // HX711 CLK pins

// --- 4個のHX711オブジェクト ---
HX711 scales[4];

void setup() {
  Serial.begin(115200);

  // 4ch分のHX711初期化
  for (int i = 0; i < 4; i++) {
    scales[i].begin(DOUT_PINS[i], SCK_PINS[i]);
  }

  delay(2000);   // 十分な安定待ち

  // 4ch分の風袋ゼロ
  for (int i = 0; i < 4; i++) {
    scales[i].tare();
  }

  // CSVヘッダ（rawデータのみ）
  Serial.println("millis,raw_ch1,raw_ch2,raw_ch3,raw_ch4");
}

void loop() {
  // 全ch準備完了チェック
  bool all_ready = true;
  for (int i = 0; i < 4; i++) {
    if (!scales[i].is_ready()) {
      all_ready = false;
      break;
    }
  }
  
  if (!all_ready) return;

  // タイムスタンプ
  Serial.print(millis());

  // 4ch分のrawデータ取得・出力
  for (int i = 0; i < 4; i++) {
    long raw = scales[i].read_average(5);  // 高速化のため5回平均
    Serial.print(",");
    Serial.print(raw);
  }
  
  Serial.println();
  
  delay(50);  // 20Hz sampling
}