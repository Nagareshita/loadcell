#pip install PySide6 pyserial matplotlib numpy

import sys
import time
import collections
import csv
import json
import os
from datetime import datetime
import numpy as np

from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QLabel, QLineEdit, QComboBox,
                               QSpinBox, QGroupBox, QGridLayout, QFileDialog,
                               QMessageBox, QStatusBar, QSplitter, QFrame,
                               QDoubleSpinBox, QButtonGroup, QRadioButton, QDialog)
from PySide6.QtCore import QTimer, Qt, Signal, QThread
from PySide6.QtGui import QFont, QIcon, QPalette, QColor

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.animation import FuncAnimation
import serial

# 日本語フォント設定（確実に存在するフォントを使用）
plt.rcParams['font.family'] = ['DejaVu Sans', 'MS Gothic', 'Yu Gothic', 'Meiryo']

class CalibrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("校正設定")
        self.setModal(True)
        self.setFixedSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # 校正モード選択
        mode_group = QGroupBox("校正モード選択")
        mode_layout = QVBoxLayout(mode_group)
        
        self.mode_group = QButtonGroup()
        self.zero_only_radio = QRadioButton("ゼロ点補正のみ")
        self.one_point_radio = QRadioButton("1点校正（推奨）")
        self.two_point_radio = QRadioButton("2点校正（高精度）")
        
        self.zero_only_radio.setChecked(True)
        
        self.mode_group.addButton(self.zero_only_radio, 0)
        self.mode_group.addButton(self.one_point_radio, 1)
        self.mode_group.addButton(self.two_point_radio, 2)
        
        mode_layout.addWidget(self.zero_only_radio)
        mode_layout.addWidget(self.one_point_radio)
        mode_layout.addWidget(self.two_point_radio)
        
        layout.addWidget(mode_group)
        
        # 校正値設定
        cal_group = QGroupBox("校正値設定")
        cal_layout = QGridLayout(cal_group)
        
        cal_layout.addWidget(QLabel("既知重量1:"), 0, 0)
        self.weight1_spin = QDoubleSpinBox()
        self.weight1_spin.setRange(0.001, 10000)
        self.weight1_spin.setValue(100.0)
        self.weight1_spin.setSuffix(" g")
        cal_layout.addWidget(self.weight1_spin, 0, 1)
        
        cal_layout.addWidget(QLabel("既知重量2:"), 1, 0)
        self.weight2_spin = QDoubleSpinBox()
        self.weight2_spin.setRange(0.001, 10000)
        self.weight2_spin.setValue(500.0)
        self.weight2_spin.setSuffix(" g")
        cal_layout.addWidget(self.weight2_spin, 1, 1)
        
        layout.addWidget(cal_group)
        
        # ボタン
        button_layout = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("キャンセル")
        
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        
        # モード変更時の処理
        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        self.on_mode_changed()
    
    def on_mode_changed(self):
        mode = self.mode_group.checkedId()
        self.weight1_spin.setEnabled(mode >= 1)
        self.weight2_spin.setEnabled(mode == 2)
    
    def get_calibration_settings(self):
        return {
            'mode': self.mode_group.checkedId(),
            'weight1': self.weight1_spin.value(),
            'weight2': self.weight2_spin.value()
        }

class SerialWorker(QThread):
    data_received = Signal(float, float)  # time, value
    error_occurred = Signal(str)
    
    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = False
        self.ser = None
        
    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            self.running = True
            
            while self.running:
                if self.ser.in_waiting:
                    line_bytes = self.ser.readline()
                    try:
                        line_str = line_bytes.decode("utf-8", errors='ignore')
                        parsed = self.parse_csv(line_str)
                        if parsed:
                            t_ms, g = parsed
                            self.data_received.emit(t_ms/1000.0, g)
                    except Exception as e:
                        continue
                self.msleep(10)
                        
        except Exception as e:
            self.error_occurred.emit(f"シリアル通信エラー: {str(e)}")
        finally:
            if self.ser:
                self.ser.close()
    
    def parse_csv(self, line_str):
        try:
            line_str = line_str.strip()
            if ',' in line_str and not line_str.startswith('millis'):
                ms_str, g_str = line_str.split(",", 1)
                return float(ms_str), float(g_str)
        except:
            pass
        return None
    
    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()

class ModernPlotWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(12, 6), facecolor='#2b2b2b')
        super().__init__(self.fig)
        self.setParent(parent)
        
        # 日本語フォント設定
        self.fig.patch.set_facecolor('#2b2b2b')
        self.ax = self.fig.add_subplot(111, facecolor='#1e1e1e')
        
        # グラフのスタイリング
        self.ax.set_xlabel('時間 [秒]', fontsize=12, color='white')
        self.ax.set_ylabel('荷重 [g]', fontsize=12, color='white')
        self.ax.set_title('リアルタイム荷重モニター', fontsize=14, color='white', pad=20)
        
        # グリッドとスパイン
        self.ax.grid(True, alpha=0.3, color='#555555')
        for spine in self.ax.spines.values():
            spine.set_color('#555555')
        self.ax.tick_params(colors='white')
        
        # データライン
        self.line, = self.ax.plot([], [], color='#00ff88', linewidth=2, alpha=0.8)
        self.fill = None
        
        self.fig.tight_layout()
        
    def update_plot(self, x_data, y_data, window_sec):
        if not x_data:
            return
            
        # データ更新
        self.line.set_data(x_data, y_data)
        
        # 軸範囲更新
        if x_data:
            xmax = max(x_data)
            xmin = max(0, xmax - window_sec)
            self.ax.set_xlim(xmin, xmax + 0.5)
            
        if y_data:
            ymin, ymax = min(y_data), max(y_data)
            if ymin == ymax:
                ymin -= 1
                ymax += 1
            pad = (ymax - ymin) * 0.1
            self.ax.set_ylim(ymin - pad, ymax + pad)
            
            # フィル効果追加
            if self.fill:
                self.fill.remove()
            self.fill = self.ax.fill_between(x_data, y_data, alpha=0.2, color='#00ff88')
        
        self.draw()
    
    def clear_plot(self):
        """グラフをクリア"""
        self.line.set_data([], [])
        if self.fill:
            self.fill.remove()
            self.fill = None
        self.ax.set_xlim(0, 30)
        self.ax.set_ylim(-10, 10)
        self.draw()

class LoadCellMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ロードセル リアルタイムモニター v2.2")
        self.setGeometry(100, 100, 1400, 900)
        
        # データバッファ
        self.buf_t = collections.deque(maxlen=5000)
        self.buf_g = collections.deque(maxlen=5000)
        self.buf_g_calibrated = collections.deque(maxlen=5000)
        
        # 時間管理
        self.start_time = None
        self.time_offset = 0
        self.recording_start_time = None  # 記録開始時刻
        
        # 校正パラメータ
        self.zero_offset = 0.0
        self.scale_factor = 1.0
        self.calibration_mode = 0  # 0: ゼロ点のみ, 1: 1点校正, 2: 2点校正
        
        # 校正データ
        self.cal_raw_zero = 0.0
        self.cal_raw_point1 = 0.0
        self.cal_raw_point2 = 0.0
        self.cal_weight1 = 100.0
        self.cal_weight2 = 500.0
        
        # 設定ファイル
        self.calibration_file = "calibration_settings.json"
        
        # 設定
        self.window_sec = 30
        self.is_recording = False
        self.recorded_data = []
        
        # ワーカースレッド
        self.serial_worker = None
        
        self.setup_ui()
        self.setup_dark_theme()
        self.load_calibration_settings()  # 起動時に校正設定読み込み
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # メインレイアウト
        main_layout = QHBoxLayout(central_widget)
        
        # サイドパネル
        side_panel = self.create_side_panel()
        side_panel.setMaximumWidth(380)
        side_panel.setMinimumWidth(350)
        
        # プロットエリア
        plot_frame = QFrame()
        plot_frame.setFrameStyle(QFrame.StyledPanel)
        plot_layout = QVBoxLayout(plot_frame)
        
        self.plot_widget = ModernPlotWidget()
        plot_layout.addWidget(self.plot_widget)
        
        # スプリッター
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(side_panel)
        splitter.addWidget(plot_frame)
        splitter.setSizes([350, 1050])
        
        main_layout.addWidget(splitter)
        
        # ステータスバー
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("待機中...")
        
        # タイマー
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(50)  # 20 FPS
        
    def create_side_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # タイトル
        title = QLabel("🔧 コントロールパネル")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 接続設定
        conn_group = QGroupBox("📡 接続設定")
        conn_layout = QGridLayout(conn_group)
        
        conn_layout.addWidget(QLabel("ポート:"), 0, 0)
        self.port_combo = QComboBox()
        self.port_combo.addItems(["COM3", "COM4", "COM5", "/dev/ttyUSB0", "/dev/ttyACM0"])
        self.port_combo.setEditable(True)
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        conn_layout.addWidget(QLabel("ボーレート:"), 1, 0)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "115200", "57600", "38400"])
        self.baud_combo.setCurrentText("115200")
        conn_layout.addWidget(self.baud_combo, 1, 1)
        
        self.connect_btn = QPushButton("🔌 接続")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn, 2, 0, 1, 2)
        
        layout.addWidget(conn_group)
        
        # 校正設定
        cal_group = QGroupBox("⚖️ 校正・補正")
        cal_layout = QVBoxLayout(cal_group)
        
        self.zero_btn = QPushButton("🎯 ゼロ点補正")
        self.zero_btn.clicked.connect(self.perform_zero_calibration)
        cal_layout.addWidget(self.zero_btn)
        
        self.calibrate_btn = QPushButton("⚙️ 校正設定")
        self.calibrate_btn.clicked.connect(self.open_calibration_dialog)
        cal_layout.addWidget(self.calibrate_btn)
        
        # 保存/読み込みボタン
        cal_save_layout = QHBoxLayout()
        self.save_cal_btn = QPushButton("💾 校正保存")
        self.load_cal_btn = QPushButton("📂 校正読み込み")
        self.save_cal_btn.clicked.connect(self.save_calibration_settings)
        self.load_cal_btn.clicked.connect(self.load_calibration_dialog)
        
        cal_save_layout.addWidget(self.save_cal_btn)
        cal_save_layout.addWidget(self.load_cal_btn)
        cal_layout.addLayout(cal_save_layout)
        
        # 校正状態表示
        self.cal_status_label = QLabel("状態: 未校正")
        self.cal_offset_label = QLabel("オフセット: 0.0")
        self.cal_scale_label = QLabel("スケール: 1.0")
        
        cal_layout.addWidget(self.cal_status_label)
        cal_layout.addWidget(self.cal_offset_label)
        cal_layout.addWidget(self.cal_scale_label)
        
        layout.addWidget(cal_group)
        
        # 表示設定
        display_group = QGroupBox("📊 表示設定")
        display_layout = QGridLayout(display_group)
        
        display_layout.addWidget(QLabel("表示時間:"), 0, 0)
        self.window_spin = QSpinBox()
        self.window_spin.setRange(5, 86400)
        self.window_spin.setValue(30)
        self.window_spin.setSuffix(" 秒")
        self.window_spin.valueChanged.connect(self.update_window_size)
        display_layout.addWidget(self.window_spin, 0, 1)
        
        # グラフクリアボタン
        self.graph_clear_btn = QPushButton("📈 グラフクリア")
        self.graph_clear_btn.clicked.connect(self.clear_graph)
        display_layout.addWidget(self.graph_clear_btn, 1, 0, 1, 2)
        
        layout.addWidget(display_group)
        
        # 統計表示
        stats_group = QGroupBox("📈 リアルタイム統計")
        stats_layout = QGridLayout(stats_group)
        
        self.current_label = QLabel("現在値: -- g")
        self.max_label = QLabel("最大値: -- g")
        self.min_label = QLabel("最小値: -- g")
        self.avg_label = QLabel("平均値: -- g")
        self.samples_label = QLabel("サンプル数: 0")
        
        stats_layout.addWidget(self.current_label, 0, 0)
        stats_layout.addWidget(self.max_label, 1, 0)
        stats_layout.addWidget(self.min_label, 2, 0)
        stats_layout.addWidget(self.avg_label, 3, 0)
        stats_layout.addWidget(self.samples_label, 4, 0)
        
        layout.addWidget(stats_group)
        
        # データ操作
        data_group = QGroupBox("💾 データ操作")
        data_layout = QVBoxLayout(data_group)
        
        self.record_btn = QPushButton("🔴 記録開始")
        self.record_btn.clicked.connect(self.toggle_recording)
        data_layout.addWidget(self.record_btn)
        
        self.save_btn = QPushButton("💾 CSVで保存")
        self.save_btn.clicked.connect(self.save_data)
        data_layout.addWidget(self.save_btn)
        
        self.clear_btn = QPushButton("🗑️ データクリア")
        self.clear_btn.clicked.connect(self.clear_data)
        data_layout.addWidget(self.clear_btn)
        
        layout.addWidget(data_group)
        
        layout.addStretch()
        return panel
    
    def setup_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: #3a3a3a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #00ff88;
            }
            QPushButton {
                background-color: #4a4a4a;
                border: 2px solid #666666;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border-color: #00ff88;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QLabel {
                color: white;
                font-size: 11px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #4a4a4a;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 4px;
                color: white;
            }
            QStatusBar {
                background-color: #3a3a3a;
                color: white;
            }
            QRadioButton {
                color: white;
            }
            QDialog {
                background-color: #2b2b2b;
                color: white;
            }
        """)
    
    def clear_graph(self):
        """グラフと時間をクリア"""
        self.buf_t.clear()
        self.buf_g.clear()
        self.buf_g_calibrated.clear()
        self.start_time = time.time()  # 現在時刻でリセット
        self.plot_widget.clear_plot()
        self.status_bar.showMessage("グラフをクリアしました - 時間リセット")
    
    def apply_calibration(self, raw_value):
        """校正を適用した値を返す"""
        if self.calibration_mode == 0:
            # ゼロ点補正のみ
            return raw_value - self.zero_offset
        elif self.calibration_mode == 1:
            # 1点校正
            return (raw_value - self.cal_raw_zero) * self.scale_factor
        elif self.calibration_mode == 2:
            # 2点校正（線形補間）
            if self.cal_raw_point2 != self.cal_raw_point1:
                slope = (self.cal_weight2 - self.cal_weight1) / (self.cal_raw_point2 - self.cal_raw_point1)
                return self.cal_weight1 + slope * (raw_value - self.cal_raw_point1)
            else:
                return raw_value - self.zero_offset
        else:
            return raw_value
    
    def perform_zero_calibration(self):
        """ゼロ点補正を実行"""
        if len(self.buf_g) < 10:
            QMessageBox.warning(self, "警告", "十分なデータがありません。接続してデータを取得してください。")
            return
        
        # 最新10個のデータの平均をゼロ点とする
        recent_data = list(self.buf_g)[-10:]
        self.zero_offset = np.mean(recent_data)
        self.calibration_mode = 0
        
        self.update_calibration_display()
        
        QMessageBox.information(self, "完了", f"ゼロ点補正を実行しました。\nオフセット: {self.zero_offset:.3f}")
        self.status_bar.showMessage("ゼロ点補正完了")
    
    def open_calibration_dialog(self):
        """校正ダイアログを開く"""
        dialog = CalibrationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = dialog.get_calibration_settings()
            self.perform_calibration(settings)
    
    def perform_calibration(self, settings):
        """校正を実行"""
        if len(self.buf_g) < 10:
            QMessageBox.warning(self, "警告", "十分なデータがありません。")
            return
        
        mode = settings['mode']
        self.calibration_mode = mode
        
        if mode == 0:
            # ゼロ点補正のみ
            self.perform_zero_calibration()
            return
        
        # 現在の値を基準点として使用
        current_raw = np.mean(list(self.buf_g)[-10:])
        
        if mode == 1:
            # 1点校正
            ret = QMessageBox.question(self, "1点校正", 
                f"現在、{settings['weight1']:.1f}gの重りを乗せていますか？", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if ret == QMessageBox.StandardButton.Yes:
                self.cal_raw_zero = self.zero_offset if hasattr(self, 'zero_offset') else 0
                self.cal_raw_point1 = current_raw
                self.cal_weight1 = settings['weight1']
                
                # スケールファクター計算
                if (current_raw - self.cal_raw_zero) != 0:
                    self.scale_factor = self.cal_weight1 / (current_raw - self.cal_raw_zero)
                else:
                    QMessageBox.warning(self, "エラー", "校正値の差が0です。ゼロ点補正を先に実行してください。")
                    return
                
                self.update_calibration_display()
                QMessageBox.information(self, "完了", "1点校正が完了しました。")
        
        elif mode == 2:
            # 2点校正
            if not hasattr(self, 'cal_raw_point1') or self.cal_raw_point1 == 0:
                # 1点目の設定
                ret = QMessageBox.question(self, "2点校正 - 1点目", 
                    f"現在、{settings['weight1']:.1f}gの重りを乗せていますか？", 
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                
                if ret == QMessageBox.StandardButton.Yes:
                    self.cal_raw_point1 = current_raw
                    self.cal_weight1 = settings['weight1']
                    QMessageBox.information(self, "1点目完了", 
                        f"1点目を記録しました。次に{settings['weight2']:.1f}gの重りに変更してもう一度校正を実行してください。")
                    return
            else:
                # 2点目の設定
                ret = QMessageBox.question(self, "2点校正 - 2点目", 
                    f"現在、{settings['weight2']:.1f}gの重りを乗せていますか？", 
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                
                if ret == QMessageBox.StandardButton.Yes:
                    self.cal_raw_point2 = current_raw
                    self.cal_weight2 = settings['weight2']
                    
                    self.update_calibration_display()
                    QMessageBox.information(self, "完了", "2点校正が完了しました。")
    
    def save_calibration_settings(self):
        """校正設定を保存"""
        if self.calibration_mode == 0 and self.zero_offset == 0:
            QMessageBox.warning(self, "警告", "保存する校正データがありません")
            return
        
        settings = {
            'calibration_mode': self.calibration_mode,
            'zero_offset': self.zero_offset,
            'scale_factor': self.scale_factor,
            'cal_raw_zero': getattr(self, 'cal_raw_zero', 0.0),
            'cal_raw_point1': getattr(self, 'cal_raw_point1', 0.0),
            'cal_raw_point2': getattr(self, 'cal_raw_point2', 0.0),
            'cal_weight1': self.cal_weight1,
            'cal_weight2': self.cal_weight2,
            'timestamp': datetime.now().isoformat()
        }
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "校正設定を保存", 
            f"calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON files (*.json)")
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "成功", f"校正設定を保存しました: {filename}")
                
                # デフォルト設定としても保存
                with open(self.calibration_file, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                    
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました: {str(e)}")
    
    def load_calibration_dialog(self):
        """校正設定読み込みダイアログ"""
        filename, _ = QFileDialog.getOpenFileName(
            self, "校正設定を読み込み", "",
            "JSON files (*.json)")
        
        if filename:
            self.load_calibration_from_file(filename)
    
    def load_calibration_settings(self):
        """起動時の校正設定読み込み"""
        if os.path.exists(self.calibration_file):
            self.load_calibration_from_file(self.calibration_file)
    
    def load_calibration_from_file(self, filename):
        """ファイルから校正設定を読み込み"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            self.calibration_mode = settings.get('calibration_mode', 0)
            self.zero_offset = settings.get('zero_offset', 0.0)
            self.scale_factor = settings.get('scale_factor', 1.0)
            self.cal_raw_zero = settings.get('cal_raw_zero', 0.0)
            self.cal_raw_point1 = settings.get('cal_raw_point1', 0.0)
            self.cal_raw_point2 = settings.get('cal_raw_point2', 0.0)
            self.cal_weight1 = settings.get('cal_weight1', 100.0)
            self.cal_weight2 = settings.get('cal_weight2', 500.0)
            
            self.update_calibration_display()
            
            timestamp = settings.get('timestamp', 'Unknown')
            QMessageBox.information(self, "読み込み完了", 
                f"校正設定を読み込みました\n保存日時: {timestamp}")
            
        except Exception as e:
            QMessageBox.warning(self, "読み込みエラー", f"校正設定の読み込みに失敗しました: {str(e)}")
    
    def update_calibration_display(self):
        """校正状態表示を更新"""
        if self.calibration_mode == 0:
            self.cal_status_label.setText("状態: ゼロ点補正済み")
            self.cal_offset_label.setText(f"オフセット: {self.zero_offset:.3f}")
            self.cal_scale_label.setText("スケール: 1.0")
        elif self.calibration_mode == 1:
            self.cal_status_label.setText("状態: 1点校正済み")
            self.cal_offset_label.setText(f"オフセット: {self.cal_raw_zero:.3f}")
            self.cal_scale_label.setText(f"スケール: {self.scale_factor:.6f}")
        elif self.calibration_mode == 2:
            self.cal_status_label.setText("状態: 2点校正済み")
            self.cal_offset_label.setText(f"点1: {self.cal_raw_point1:.3f}→{self.cal_weight1:.1f}g")
            self.cal_scale_label.setText(f"点2: {self.cal_raw_point2:.3f}→{self.cal_weight2:.1f}g")
        else:
            self.cal_status_label.setText("状態: 未校正")
            self.cal_offset_label.setText("オフセット: --")
            self.cal_scale_label.setText("スケール: --")
    
    def toggle_connection(self):
        if self.serial_worker and self.serial_worker.isRunning():
            self.disconnect_serial()
        else:
            self.connect_serial()
    
    def connect_serial(self):
        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        
        self.serial_worker = SerialWorker(port, baud)
        self.serial_worker.data_received.connect(self.on_data_received)
        self.serial_worker.error_occurred.connect(self.on_error)
        self.serial_worker.start()
        
        self.connect_btn.setText("🔌 切断")
        self.connect_btn.setStyleSheet("background-color: #ff4444;")
        self.status_bar.showMessage(f"接続中: {port} @ {baud} bps")
    
    def disconnect_serial(self):
        if self.serial_worker:
            self.serial_worker.stop()
            self.serial_worker.wait()
            self.serial_worker = None
        
        self.connect_btn.setText("🔌 接続")
        self.connect_btn.setStyleSheet("")
        self.status_bar.showMessage("切断されました")
    
    def on_data_received(self, t, g):
        # 簡潔で確実な時間管理（接続時間）
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
        
        # アプリ起動からの経過時間（秒）
        relative_time = current_time - self.start_time
        
        self.buf_t.append(relative_time)
        self.buf_g.append(g)
        
        # 校正適用
        g_calibrated = self.apply_calibration(g)
        self.buf_g_calibrated.append(g_calibrated)
        
        if self.is_recording and self.recording_start_time is not None:
            # 🆕 Windowsタイムスタンプ（高精度）
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # 🆕 記録開始からの経過時間
            recording_time = current_time - self.recording_start_time
            
            self.recorded_data.append([timestamp, recording_time, g, g_calibrated])
    
    def on_error(self, error_msg):
        QMessageBox.critical(self, "エラー", error_msg)
        self.disconnect_serial()
    
    def update_display(self):
        if not self.buf_t:
            return
        
        # 表示範囲のデータ抽出（校正済みデータを使用）
        tmax = self.buf_t[-1]
        tmin = max(0, tmax - self.window_sec)
        
        x_data = [t for t in self.buf_t if t >= tmin]
        y_data_raw = list(self.buf_g_calibrated)[len(self.buf_t)-len(x_data):]
        
        # プロット更新
        self.plot_widget.update_plot(x_data, y_data_raw, self.window_sec)
        
        # 統計更新（校正済みデータ）
        if y_data_raw:
            current = y_data_raw[-1]
            maximum = max(y_data_raw)
            minimum = min(y_data_raw)
            average = np.mean(y_data_raw)
            
            self.current_label.setText(f"現在値: {current:.2f} g")
            self.max_label.setText(f"最大値: {maximum:.2f} g")
            self.min_label.setText(f"最小値: {minimum:.2f} g")
            self.avg_label.setText(f"平均値: {average:.2f} g")
            self.samples_label.setText(f"サンプル数: {len(self.buf_g)}")
    
    def update_window_size(self):
        self.window_sec = self.window_spin.value()
    
    def toggle_recording(self):
        if self.is_recording:
            self.is_recording = False
            self.record_btn.setText("🔴 記録開始")
            self.record_btn.setStyleSheet("")
            self.status_bar.showMessage("記録停止")
            self.recording_start_time = None  # 🆕 記録時間をリセット
        else:
            self.is_recording = True
            self.recorded_data = []
            self.recording_start_time = time.time()  # 🆕 記録開始時刻を記録
            self.record_btn.setText("⏹️ 記録停止")
            self.record_btn.setStyleSheet("background-color: #ff4444;")
            self.status_bar.showMessage("記録中...")
    
    def save_data(self):
        if not self.recorded_data:
            QMessageBox.warning(self, "警告", "保存するデータがありません")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "データを保存", f"loadcell_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV files (*.csv)")
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # 🆕 より分かりやすいヘッダー
                    writer.writerow(['Windows_Timestamp', 'Recording_Time_s', 'Raw_Value', 'Calibrated_g'])
                    writer.writerows(self.recorded_data)
                QMessageBox.information(self, "成功", f"データを保存しました: {filename}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました: {str(e)}")
    
    def clear_data(self):
        reply = QMessageBox.question(self, "確認", "全てのデータをクリアしますか？")
        if reply == QMessageBox.StandardButton.Yes:
            self.buf_t.clear()
            self.buf_g.clear()
            self.buf_g_calibrated.clear()
            self.recorded_data = []
            self.status_bar.showMessage("データをクリアしました")
    
    def closeEvent(self, event):
        self.disconnect_serial()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # モダンなスタイル
    
    # 日本語フォント設定（確実に存在するフォントを使用）
    font = QFont()
    if sys.platform == "win32":
        font.setFamily("MS UI Gothic")  # Windowsで確実に存在
    elif sys.platform == "darwin":
        font.setFamily("Arial Unicode MS")  # macOSで確実に存在
    else:
        font.setFamily("DejaVu Sans")  # Linuxで確実に存在
    app.setFont(font)
    
    window = LoadCellMonitor()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()