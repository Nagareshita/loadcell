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
                               QDoubleSpinBox, QButtonGroup, QRadioButton, QDialog,
                               QCheckBox, QTabWidget, QTextEdit, QScrollArea, QInputDialog)
from PySide6.QtCore import QTimer, Qt, Signal, QThread
from PySide6.QtGui import QFont, QIcon, QPalette, QColor

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.animation import FuncAnimation
import serial

# 日本語フォント設定
plt.rcParams['font.family'] = ['DejaVu Sans', 'MS Gothic', 'Yu Gothic', 'Meiryo']

class ChannelCalibration:
    """HX711標準校正方式に完全準拠した校正クラス"""
    def __init__(self):
        self.zero_point = 0.0           # Tare時のraw値
        self.calibration_factor = 1000.0  # 初期値（従来のcalibration_factor）
        self.is_calibrated = False      # 校正済みフラグ
        self.is_tared = False          # ゼロ点設定済みフラグ
    
    def tare(self, raw_values):
        """ゼロ点設定（風袋引き）"""
        if len(raw_values) < 5:
            raise ValueError("データが不足しています")
        
        self.zero_point = np.mean(raw_values)
        self.is_tared = True
        
    def calibrate_with_weight(self, raw_values, known_weight):
        """既知重量での校正"""
        if not self.is_tared:
            raise ValueError("先にゼロ点設定（Tare）を実行してください")
        
        if known_weight <= 0:
            raise ValueError("重量は正の値である必要があります")
        
        if len(raw_values) < 5:
            raise ValueError("データが不足しています")
        
        current_raw = np.mean(raw_values)
        raw_change = current_raw - self.zero_point
        
        if abs(raw_change) < 10:  # 変化が小さすぎる
            raise ValueError("重量変化が検出できません。より重い重りを使用してください")
        
        # HX711標準公式: calibration_factor = raw値の変化 / 既知重量
        self.calibration_factor = raw_change / known_weight
        self.is_calibrated = True
    
    def get_weight(self, raw_value):
        """HX711標準公式: Weight(g) = (RawValue - ZeroPoint) / CalibrationFactor"""
        if not self.is_tared:
            return 0.0  # ゼロ点未設定時は0を返す
        
        return (raw_value - self.zero_point) / self.calibration_factor
    
    def to_dict(self):
        """辞書形式でエクスポート"""
        return {
            'zero_point': self.zero_point,
            'calibration_factor': self.calibration_factor,
            'is_calibrated': self.is_calibrated,
            'is_tared': self.is_tared
        }
    
    def from_dict(self, data):
        """辞書から読み込み"""
        self.zero_point = data.get('zero_point', 0.0)
        self.calibration_factor = data.get('calibration_factor', 1000.0)
        self.is_calibrated = data.get('is_calibrated', False)
        self.is_tared = data.get('is_tared', False)

class SerialWorker(QThread):
    data_received = Signal(float, list)  # time, [raw_ch1, raw_ch2, raw_ch3, raw_ch4]
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
                            t_ms, ch_data = parsed
                            self.data_received.emit(t_ms/1000.0, ch_data)
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
                parts = line_str.split(",")
                if len(parts) >= 5:  # millis + 4ch
                    ms_str = parts[0]
                    ch_data = [float(parts[i]) for i in range(1, 5)]
                    return float(ms_str), ch_data
        except:
            pass
        return None
    
    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()

class MultiChannelPlotWidget(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(14, 8), facecolor='#2b2b2b')
        super().__init__(self.fig)
        self.setParent(parent)
        
        # 4チャンネル分のサブプロット
        self.axes = []
        self.lines = []
        self.fills = []
        
        colors = ['#00ff88', '#ff6b6b', '#4ecdc4', '#ffe66d']
        
        for i in range(4):
            ax = self.fig.add_subplot(2, 2, i+1, facecolor='#1e1e1e')
            ax.set_xlabel('時間 [秒]', fontsize=10, color='white')
            ax.set_ylabel('荷重 [g]', fontsize=10, color='white')
            ax.set_title(f'CH{i+1} リアルタイム荷重', fontsize=12, color='white')
            
            # グリッドとスパイン
            ax.grid(True, alpha=0.3, color='#555555')
            for spine in ax.spines.values():
                spine.set_color('#555555')
            ax.tick_params(colors='white', labelsize=8)
            
            # データライン
            line, = ax.plot([], [], color=colors[i], linewidth=2, alpha=0.8)
            
            self.axes.append(ax)
            self.lines.append(line)
            self.fills.append(None)
        
        self.fig.tight_layout(pad=2.0)
        
    def update_plot(self, x_data, y_data_channels, window_sec, enabled_channels):
        if not x_data:
            return
            
        for ch in range(4):
            if not enabled_channels[ch]:
                # 無効なチャンネルはクリア
                self.lines[ch].set_data([], [])
                if self.fills[ch]:
                    self.fills[ch].remove()
                    self.fills[ch] = None
                self.axes[ch].set_xlim(0, window_sec)
                self.axes[ch].set_ylim(-10, 10)
                continue
            
            y_data = y_data_channels[ch]
            
            # データ更新
            self.lines[ch].set_data(x_data, y_data)
            
            # 軸範囲更新
            if x_data:
                xmax = max(x_data)
                xmin = max(0, xmax - window_sec)
                self.axes[ch].set_xlim(xmin, xmax + 0.5)
                
            if y_data:
                ymin, ymax = min(y_data), max(y_data)
                if ymin == ymax:
                    ymin -= 1
                    ymax += 1
                pad = (ymax - ymin) * 0.1
                self.axes[ch].set_ylim(ymin - pad, ymax + pad)
                
                # フィル効果追加
                if self.fills[ch]:
                    self.fills[ch].remove()
                colors = ['#00ff88', '#ff6b6b', '#4ecdc4', '#ffe66d']
                self.fills[ch] = self.axes[ch].fill_between(x_data, y_data, alpha=0.2, color=colors[ch])
        
        self.draw()
    
    def clear_plot(self):
        """グラフをクリア"""
        for ch in range(4):
            self.lines[ch].set_data([], [])
            if self.fills[ch]:
                self.fills[ch].remove()
                self.fills[ch] = None
            self.axes[ch].set_xlim(0, 30)
            self.axes[ch].set_ylim(-10, 10)
        self.draw()

class LoadCellMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("4チャンネル ロードセル モニター v3.1 - HX711標準校正対応")
        self.setGeometry(100, 100, 1600, 1000)
        
        # 4チャンネル分のデータバッファ
        self.buf_t = collections.deque(maxlen=5000)
        self.buf_raw = [collections.deque(maxlen=5000) for _ in range(4)]  # 4ch分のRawデータ
        self.buf_calibrated = [collections.deque(maxlen=5000) for _ in range(4)]  # 4ch分の校正済みデータ
        
        # チャンネル有効/無効
        self.channel_enabled = [True, True, True, True]
        
        # 🆕 HX711標準校正方式対応
        self.calibrations = [ChannelCalibration() for _ in range(4)]
        
        # 時間管理
        self.start_time = None
        self.recording_start_time = None
        
        # 設定
        self.window_sec = 30
        self.is_recording = False
        self.recorded_data = []
        
        # ワーカースレッド
        self.serial_worker = None
        
        self.setup_ui()
        self.setup_dark_theme()
        self.load_calibration_settings()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # メインレイアウト
        main_layout = QHBoxLayout(central_widget)
        
        # コントロールパネル（タブ付き）
        control_panel = self.create_control_panel()
        control_panel.setMaximumWidth(400)
        control_panel.setMinimumWidth(380)
        
        # プロットエリア
        plot_frame = QFrame()
        plot_frame.setFrameStyle(QFrame.StyledPanel)
        plot_layout = QVBoxLayout(plot_frame)
        
        self.plot_widget = MultiChannelPlotWidget()
        plot_layout.addWidget(self.plot_widget)
        
        # スプリッター
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(control_panel)
        splitter.addWidget(plot_frame)
        splitter.setSizes([400, 1200])
        
        main_layout.addWidget(splitter)
        
        # ステータスバー
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("待機中...")
        
        # タイマー
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(50)  # 20 FPS
    
    def create_control_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # タブウィジェット
        tab_widget = QTabWidget()
        
        # 接続タブ
        connection_tab = self.create_connection_tab()
        tab_widget.addTab(connection_tab, "🔌 接続")
        
        # チャンネル設定タブ
        channel_tab = self.create_channel_tab()
        tab_widget.addTab(channel_tab, "📊 チャンネル")
        
        # 校正タブ
        calibration_tab = self.create_calibration_tab()
        tab_widget.addTab(calibration_tab, "⚖️ 校正")
        
        # データタブ
        data_tab = self.create_data_tab()
        tab_widget.addTab(data_tab, "💾 データ")
        
        layout.addWidget(tab_widget)
        return panel
    
    def create_connection_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        
        self.graph_clear_btn = QPushButton("📈 グラフクリア")
        self.graph_clear_btn.clicked.connect(self.clear_graph)
        display_layout.addWidget(self.graph_clear_btn, 1, 0, 1, 2)
        
        layout.addWidget(display_group)
        layout.addStretch()
        return tab
    
    def create_channel_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # チャンネル選択
        channel_group = QGroupBox("📊 使用チャンネル選択")
        channel_layout = QVBoxLayout(channel_group)
        
        self.channel_checkboxes = []
        for i in range(4):
            checkbox = QCheckBox(f"CH{i+1} 使用")
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(lambda state, ch=i: self.toggle_channel(ch, state))
            self.channel_checkboxes.append(checkbox)
            channel_layout.addWidget(checkbox)
        
        layout.addWidget(channel_group)
        
        # 統計表示（4ch分）
        stats_group = QGroupBox("📈 リアルタイム統計")
        stats_layout = QVBoxLayout(stats_group)
        
        # スクロールエリア
        scroll = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.stats_labels = []
        for i in range(4):
            ch_frame = QFrame()
            ch_frame.setFrameStyle(QFrame.Box)
            ch_layout = QVBoxLayout(ch_frame)
            
            ch_title = QLabel(f"📊 CH{i+1}")
            ch_title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            ch_layout.addWidget(ch_title)
            
            labels = {
                'current': QLabel("現在値: -- g"),
                'max': QLabel("最大値: -- g"),
                'min': QLabel("最小値: -- g"),
                'avg': QLabel("平均値: -- g")
            }
            
            for label in labels.values():
                label.setFont(QFont("Arial", 8))
                ch_layout.addWidget(label)
            
            self.stats_labels.append(labels)
            scroll_layout.addWidget(ch_frame)
        
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        stats_layout.addWidget(scroll)
        
        layout.addWidget(stats_group)
        layout.addStretch()
        return tab
    
    def create_calibration_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # チャンネル別校正
        cal_group = QGroupBox("⚖️ HX711標準校正方式")
        cal_layout = QVBoxLayout(cal_group)
        
        # 校正手順説明
        info_label = QLabel("📋 校正手順:\n①ゼロ点設定 → ②既知重量で校正")
        info_label.setFont(QFont("Arial", 9))
        info_label.setStyleSheet("color: #00ff88; margin: 5px;")
        cal_layout.addWidget(info_label)
        
        # 4ch分の校正ボタン
        self.calibration_buttons = []
        self.calibration_status_labels = []
        
        for i in range(4):
            ch_frame = QFrame()
            ch_frame.setFrameStyle(QFrame.Box)
            ch_layout = QVBoxLayout(ch_frame)
            
            ch_title = QLabel(f"📊 CH{i+1}")
            ch_title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            ch_layout.addWidget(ch_title)
            
            button_layout = QHBoxLayout()
            
            # 🆕 ゼロ点設定（Tare）ボタン
            tare_btn = QPushButton(f"🎯 Tare")
            tare_btn.clicked.connect(lambda checked, ch=i: self.perform_tare(ch))
            button_layout.addWidget(tare_btn)
            
            # 🆕 重量校正ボタン
            cal_btn = QPushButton(f"⚙️ 校正")
            cal_btn.clicked.connect(lambda checked, ch=i: self.open_weight_calibration_dialog(ch))
            button_layout.addWidget(cal_btn)
            
            ch_layout.addLayout(button_layout)
            
            # 🆕 校正状態表示
            status_label = QLabel("状態: 未校正\nゼロ点: --\n係数: 1000.0 (初期値)")
            status_label.setFont(QFont("Arial", 8))
            ch_layout.addWidget(status_label)
            
            self.calibration_buttons.append([tare_btn, cal_btn])
            self.calibration_status_labels.append(status_label)
            cal_layout.addWidget(ch_frame)
        
        layout.addWidget(cal_group)
        
        # 校正データ保存/読み込み
        file_group = QGroupBox("💾 校正ファイル操作")
        file_layout = QGridLayout(file_group)
        
        self.save_cal_btn = QPushButton("💾 全校正保存")
        self.load_cal_btn = QPushButton("📂 校正読み込み")
        
        self.save_cal_btn.clicked.connect(self.save_calibration_settings)
        self.load_cal_btn.clicked.connect(self.load_calibration_dialog)
        
        file_layout.addWidget(self.save_cal_btn, 0, 0)
        file_layout.addWidget(self.load_cal_btn, 0, 1)
        
        layout.addWidget(file_group)
        layout.addStretch()
        return tab
    
    def create_data_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        
        # データ情報
        info_group = QGroupBox("ℹ️ データ情報")
        info_layout = QVBoxLayout(info_group)
        
        self.samples_label = QLabel("総サンプル数: 0")
        self.recording_label = QLabel("記録サンプル数: 0")
        
        info_layout.addWidget(self.samples_label)
        info_layout.addWidget(self.recording_label)
        
        layout.addWidget(info_group)
        layout.addStretch()
        return tab
    
    def setup_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: white;
            }
            QTabWidget::pane {
                border: 2px solid #555555;
                background-color: #3a3a3a;
            }
            QTabBar::tab {
                background-color: #4a4a4a;
                color: white;
                padding: 8px 12px;
                margin-right: 2px;
                border-radius: 4px 4px 0 0;
            }
            QTabBar::tab:selected {
                background-color: #00ff88;
                color: black;
                font-weight: bold;
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
            QCheckBox {
                color: white;
                font-weight: bold;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #666666;
                background-color: #4a4a4a;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #00ff88;
                background-color: #00ff88;
                border-radius: 4px;
            }
            QFrame {
                border: 1px solid #555555;
                border-radius: 4px;
                background-color: #2b2b2b;
                margin: 2px;
                padding: 4px;
            }
            QScrollArea {
                border: none;
                background-color: #3a3a3a;
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
    
    def toggle_channel(self, channel, state):
        """チャンネルの有効/無効を切り替え"""
        self.channel_enabled[channel] = (state == Qt.CheckState.Checked.value)
        enabled_text = "有効" if self.channel_enabled[channel] else "無効"
        self.status_bar.showMessage(f"CH{channel+1} を{enabled_text}にしました")
    
    # 🆕 HX711標準校正方式
    def apply_calibration(self, raw_value, channel):
        """HX711標準公式でraw値から重量を計算"""
        return self.calibrations[channel].get_weight(raw_value)
    
    def perform_tare(self, channel):
        """ゼロ点設定（Tare）"""
        if len(self.buf_raw[channel]) < 10:
            QMessageBox.warning(self, "警告", f"CH{channel+1}: 十分なデータがありません。")
            return
        
        try:
            recent_data = list(self.buf_raw[channel])[-10:]
            self.calibrations[channel].tare(recent_data)
            
            self.update_calibration_display(channel)
            QMessageBox.information(self, "Tare完了", 
                f"CH{channel+1} ゼロ点設定完了\n"
                f"ゼロ点: {self.calibrations[channel].zero_point:.1f}")
            
        except ValueError as e:
            QMessageBox.warning(self, "Tareエラー", str(e))
    
    def open_weight_calibration_dialog(self, channel):
        """重量校正ダイアログ"""
        if not self.calibrations[channel].is_tared:
            QMessageBox.warning(self, "警告", f"CH{channel+1}: 先にTare（ゼロ点設定）を実行してください。")
            return
        
        # シンプルな重量入力ダイアログ
        weight, ok = QInputDialog.getDouble(
            self, f"CH{channel+1} 重量校正", 
            "既知重量を入力してください (g):", 
            100.0, 0.1, 10000.0, 1)
        
        if ok:
            ret = QMessageBox.question(self, "校正確認", 
                f"CH{channel+1}に{weight:.1f}gの重りを乗せましたか？")
            
            if ret == QMessageBox.StandardButton.Yes:
                self.perform_weight_calibration(channel, weight)
    
    def perform_weight_calibration(self, channel, known_weight):
        """重量校正実行"""
        if len(self.buf_raw[channel]) < 10:
            QMessageBox.warning(self, "警告", f"CH{channel+1}: 十分なデータがありません。")
            return
        
        try:
            recent_data = list(self.buf_raw[channel])[-10:]
            self.calibrations[channel].calibrate_with_weight(recent_data, known_weight)
            
            self.update_calibration_display(channel)
            QMessageBox.information(self, "校正完了", 
                f"CH{channel+1} 校正完了\n"
                f"校正係数: {self.calibrations[channel].calibration_factor:.1f}")
            
        except ValueError as e:
            QMessageBox.warning(self, "校正エラー", str(e))
    
    def save_calibration_settings(self):
        """全チャンネルの校正設定を保存"""
        settings = {
            'channels': [cal.to_dict() for cal in self.calibrations],
            'channel_enabled': self.channel_enabled,
            'timestamp': datetime.now().isoformat()
        }
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "校正設定を保存", 
            f"calibration_4ch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON files (*.json)")
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "成功", f"4ch校正設定を保存しました: {filename}")
                
                # デフォルト設定としても保存
                with open("calibration_4ch_settings.json", 'w', encoding='utf-8') as f:
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
        filename = "calibration_4ch_settings.json"
        if os.path.exists(filename):
            self.load_calibration_from_file(filename)
    
    def load_calibration_from_file(self, filename):
        """ファイルから校正設定を読み込み"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            if 'channels' in settings:
                for i, cal_data in enumerate(settings['channels']):
                    if i < 4:
                        self.calibrations[i].from_dict(cal_data)
            
            if 'channel_enabled' in settings:
                self.channel_enabled = settings['channel_enabled']
                for i, enabled in enumerate(self.channel_enabled):
                    if i < len(self.channel_checkboxes):
                        self.channel_checkboxes[i].setChecked(enabled)
            
            # 校正状態表示を更新
            for ch in range(4):
                self.update_calibration_display(ch)
            
            timestamp = settings.get('timestamp', 'Unknown')
            QMessageBox.information(self, "読み込み完了", 
                f"4ch校正設定を読み込みました\n保存日時: {timestamp}")
            
        except Exception as e:
            QMessageBox.warning(self, "読み込みエラー", f"校正設定の読み込みに失敗しました: {str(e)}")
    
    def update_calibration_display(self, channel):
        """校正状態表示更新"""
        cal = self.calibrations[channel]
        label = self.calibration_status_labels[channel]
        
        if cal.is_calibrated:
            label.setText(
                f"状態: 校正済み ✅\n"
                f"ゼロ点: {cal.zero_point:.1f}\n"
                f"係数: {cal.calibration_factor:.1f}")
        elif cal.is_tared:
            label.setText(
                f"状態: Tare済み 🎯\n"
                f"ゼロ点: {cal.zero_point:.1f}\n"
                f"係数: {cal.calibration_factor:.1f} (初期値)")
        else:
            label.setText(
                f"状態: 未校正 ❌\n"
                f"ゼロ点: --\n"
                f"係数: {cal.calibration_factor:.1f} (初期値)")
    
    def clear_graph(self):
        """グラフと時間をクリア"""
        self.buf_t.clear()
        for ch in range(4):
            self.buf_raw[ch].clear()
            self.buf_calibrated[ch].clear()
        self.start_time = time.time()
        self.plot_widget.clear_plot()
        self.status_bar.showMessage("全グラフをクリア - 時間リセット")
    
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
    
    def on_data_received(self, t, raw_data):
        """4チャンネル分のデータを受信"""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
        
        relative_time = current_time - self.start_time
        self.buf_t.append(relative_time)
        
        # 4ch分のデータ処理
        for ch in range(4):
            raw_value = raw_data[ch]
            self.buf_raw[ch].append(raw_value)
            
            # 🆕 HX711標準校正適用
            calibrated_value = self.apply_calibration(raw_value, ch)
            self.buf_calibrated[ch].append(calibrated_value)
        
        # 記録処理
        if self.is_recording and self.recording_start_time is not None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            recording_time = current_time - self.recording_start_time
            
            # 全チャンネルのデータを記録
            row_data = [timestamp, recording_time]
            for ch in range(4):
                row_data.extend([raw_data[ch], self.buf_calibrated[ch][-1]])
            
            self.recorded_data.append(row_data)
    
    def on_error(self, error_msg):
        QMessageBox.critical(self, "エラー", error_msg)
        self.disconnect_serial()
    
    def update_display(self):
        if not self.buf_t:
            return
        
        # 表示範囲のデータ抽出
        tmax = self.buf_t[-1]
        tmin = max(0, tmax - self.window_sec)
        
        x_data = [t for t in self.buf_t if t >= tmin]
        
        # 4ch分の表示データ準備
        y_data_channels = []
        for ch in range(4):
            if self.channel_enabled[ch]:
                y_data = list(self.buf_calibrated[ch])[len(self.buf_t)-len(x_data):]
            else:
                y_data = []
            y_data_channels.append(y_data)
        
        # プロット更新
        self.plot_widget.update_plot(x_data, y_data_channels, self.window_sec, self.channel_enabled)
        
        # 統計更新
        for ch in range(4):
            if self.channel_enabled[ch] and y_data_channels[ch]:
                y_data = y_data_channels[ch]
                current = y_data[-1]
                maximum = max(y_data)
                minimum = min(y_data)
                average = np.mean(y_data)
                
                labels = self.stats_labels[ch]
                labels['current'].setText(f"現在値: {current:.2f} g")
                labels['max'].setText(f"最大値: {maximum:.2f} g")
                labels['min'].setText(f"最小値: {minimum:.2f} g")
                labels['avg'].setText(f"平均値: {average:.2f} g")
            else:
                labels = self.stats_labels[ch]
                for label in labels.values():
                    label.setText("-- g")
        
        # サンプル数更新
        self.samples_label.setText(f"総サンプル数: {len(self.buf_t)}")
        self.recording_label.setText(f"記録サンプル数: {len(self.recorded_data)}")
    
    def update_window_size(self):
        self.window_sec = self.window_spin.value()
    
    def toggle_recording(self):
        if self.is_recording:
            self.is_recording = False
            self.record_btn.setText("🔴 記録開始")
            self.record_btn.setStyleSheet("")
            self.status_bar.showMessage("記録停止")
            self.recording_start_time = None
        else:
            self.is_recording = True
            self.recorded_data = []
            self.recording_start_time = time.time()
            self.record_btn.setText("⏹️ 記録停止")
            self.record_btn.setStyleSheet("background-color: #ff4444;")
            self.status_bar.showMessage("記録中...")
    
    def save_data(self):
        if not self.recorded_data:
            QMessageBox.warning(self, "警告", "保存するデータがありません")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "4chデータを保存", f"loadcell_4ch_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV files (*.csv)")
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # 4ch対応ヘッダー
                    header = ['Windows_Timestamp', 'Recording_Time_s']
                    for ch in range(4):
                        header.extend([f'Raw_CH{ch+1}', f'Calibrated_CH{ch+1}_g'])
                    writer.writerow(header)
                    writer.writerows(self.recorded_data)
                QMessageBox.information(self, "成功", f"4chデータを保存しました: {filename}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"保存に失敗しました: {str(e)}")
    
    def clear_data(self):
        reply = QMessageBox.question(self, "確認", "全てのデータをクリアしますか？")
        if reply == QMessageBox.StandardButton.Yes:
            self.buf_t.clear()
            for ch in range(4):
                self.buf_raw[ch].clear()
                self.buf_calibrated[ch].clear()
            self.recorded_data = []
            self.status_bar.showMessage("全データをクリアしました")
    
    def closeEvent(self, event):
        self.disconnect_serial()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 日本語フォント設定
    font = QFont()
    if sys.platform == "win32":
        font.setFamily("MS UI Gothic")
    elif sys.platform == "darwin":
        font.setFamily("Arial Unicode MS")
    else:
        font.setFamily("DejaVu Sans")
    app.setFont(font)
    
    window = LoadCellMonitor()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()