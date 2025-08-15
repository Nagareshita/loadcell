// --- 1) ライブラリ取り込み ---
#include "HX711.h"

// --- 2) ピン定義（衝突回避のため名前を変更） ---
const int HX_DOUT_PIN = 8;   // HX711のDAT → Arduino D8（入力）
const int HX_SCK_PIN  = 9;   // HX711のCLK → Arduino D9（出力）

// --- 3) HX711オブジェクト ---
HX711 scale;

// --- 4) 校正係数 ---
float calibration_factor = 1000.0f;

void setup() {
  Serial.begin(115200);

  // HX711初期化（ピン指定）
  scale.begin(HX_DOUT_PIN, HX_SCK_PIN);

  delay(1000);   // 安定待ち
  scale.tare();  // 風袋ゼロ

  Serial.println("millis,grams"); // CSVヘッダ
}

void loop() {
  // 新データ準備待ち
  if (!scale.is_ready()) return;

  // 10回平均でノイズ低減
  long raw = scale.read_average(10);

  // g換算（後で調整）
  double grams = raw / calibration_factor;

  // CSVで出力
  Serial.print(millis());
  Serial.print(",");
  Serial.println(grams, 3);
}
