#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  app.py  —  KeyValue Game Localization AI Translator (PyQt6)  •  PS5VietHoa (Phước Lê & Mèo Mặt Căng)
#  GUI dịch text game EN->VI: cấu hình API 2 format (OpenAI/Anthropic), tự sinh
#  system prompt theo tên game + file EN, dịch đa luồng + TRỰC QUAN HÓA tiến độ.
#  Engine ở engine.py (thuần stdlib). Chạy:  python3 app.py   (hoặc ./run_tool.command)
# ============================================================================
import os, sys, json, threading, time

from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QObject, QTimer, QRect,
                          QAbstractTableModel, QModelIndex, QSortFilterProxyModel)
from PyQt6.QtGui import QPainter, QColor, QFont, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QComboBox,
    QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup, QFileDialog, QFrame,
    QTableWidget, QTableWidgetItem, QTableView, QHeaderView, QProgressBar, QMessageBox,
    QSizePolicy, QToolTip, QCompleter, QCheckBox, QScrollArea,
)

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import engine as E

CONFIG_PATH = os.path.join(BASE, 'config.json')
LANGS = ('vi', 'en')                          # ngôn ngữ giao diện hỗ trợ
LANG_NAMES = ['Tiếng Việt', 'English']        # nhãn hiển thị (endonym) trong bộ chuyển

# ---- bảng màu (Slate trung tính — Tailwind • KHÔNG emoji) ----
BG='#0f172a'; CARD='#1e293b'; ENTRY='#0b1220'; FG='#e2e8f0'; MUTED='#94a3b8'; DIM='#64748b'
ACC='#38bdf8'; ACC2='#0ea5e9'; GREEN='#34d399'; RED='#fb7185'; YEL='#fbbf24'; ORANGE='#f59e0b'
BORDER='#334155'; BORDER2='#475569'; INK='#04121f'

ST_QUEUED, ST_RUNNING, ST_DONE, ST_ERROR, ST_RETRY = 0, 1, 2, 3, 4
STATE_NUM = {'queued': ST_QUEUED, 'running': ST_RUNNING, 'done': ST_DONE,
             'error': ST_ERROR, 'retry': ST_RETRY}
STATE_COLOR = {ST_QUEUED: QColor(BORDER), ST_RUNNING: QColor(YEL), ST_DONE: QColor(GREEN),
               ST_ERROR: QColor(RED), ST_RETRY: QColor(ORANGE)}
STATE_NAME = {ST_QUEUED: 'chờ', ST_RUNNING: 'đang dịch', ST_DONE: 'xong',
              ST_ERROR: 'lỗi', ST_RETRY: 'thử lại'}

QSS = f"""
QWidget {{ background:{BG}; color:{FG};
    font-family:'Inter','SF Pro Text','Segoe UI','Helvetica Neue',sans-serif; font-size:13px; }}
QToolTip {{ background:{CARD}; color:{FG}; border:1px solid {BORDER}; border-radius:6px; padding:6px 8px; }}

QTabWidget::pane {{ border:1px solid {BORDER}; border-radius:12px; top:-1px; background:{BG}; }}
QTabBar::tab {{ background:transparent; color:{MUTED}; padding:9px 20px; margin-right:4px;
    border:1px solid transparent; border-top-left-radius:9px; border-top-right-radius:9px; font-weight:600; }}
QTabBar::tab:hover {{ color:{FG}; }}
QTabBar::tab:selected {{ background:{CARD}; color:{ACC}; border:1px solid {BORDER}; border-bottom-color:{CARD}; }}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background:{ENTRY}; color:{FG}; border:1px solid {BORDER}; border-radius:8px; padding:7px 10px;
    selection-background-color:{ACC}; selection-color:{INK}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border:1px solid {BORDER2}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border:1px solid {ACC}; }}
QComboBox::drop-down {{ border:0; width:24px; }}
QComboBox QAbstractItemView {{ background:{ENTRY}; color:{FG}; selection-background-color:{ACC};
    selection-color:{INK}; border:1px solid {BORDER}; border-radius:8px; padding:4px; outline:0; }}

QPushButton {{ background:{CARD}; color:{FG}; border:1px solid {BORDER}; border-radius:8px;
    padding:8px 16px; font-weight:600; }}
QPushButton:hover {{ background:{BORDER}; border-color:{BORDER2}; }}
QPushButton:pressed {{ background:{ENTRY}; }}
QPushButton:disabled {{ background:{CARD}; color:{DIM}; border-color:{BORDER}; }}
QPushButton#primary {{ background:{GREEN}; color:{INK}; border:0; font-size:14px; padding:10px 22px; }}
QPushButton#primary:hover {{ background:#5eead4; }}
QPushButton#primary:disabled {{ background:#1f3b34; color:{DIM}; }}
QPushButton#accent {{ background:{ACC}; color:{INK}; border:0; }}
QPushButton#accent:hover {{ background:#7dd3fc; }}
QPushButton#danger {{ background:{RED}; color:{INK}; border:0; }}
QPushButton#danger:hover {{ background:#fda4af; }}
QPushButton#danger:disabled {{ background:#3a2230; color:{DIM}; }}

QLabel {{ background:transparent; }}
QLabel#h {{ font-size:15px; font-weight:700; color:{FG}; }}
QLabel#muted {{ color:{MUTED}; }}

QFrame#card {{ background:{CARD}; border:1px solid {BORDER}; border-radius:12px; }}
QFrame#stat {{ background:{CARD}; border:1px solid {BORDER}; border-radius:12px; }}
QFrame#sep {{ background:{BORDER}; border:0; max-height:1px; min-height:1px; }}

QTableWidget, QTableView {{ background:{ENTRY}; gridline-color:{BORDER}; border:1px solid {BORDER};
    border-radius:10px; }}
QTableView::item, QTableWidget::item {{ padding:2px 4px; }}
QTableView::item:selected, QTableWidget::item:selected {{ background:{BORDER}; color:{FG}; }}
QHeaderView::section {{ background:{CARD}; color:{MUTED}; border:0; border-bottom:1px solid {BORDER};
    padding:8px; font-weight:700; }}
QTableCornerButton::section {{ background:{CARD}; border:0; }}

QProgressBar {{ background:{ENTRY}; border:1px solid {BORDER}; border-radius:9px; height:24px;
    text-align:center; color:{FG}; font-weight:700; }}
QProgressBar::chunk {{ border-radius:8px;
    background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACC}, stop:1 {GREEN}); }}

QCheckBox, QRadioButton {{ spacing:8px; background:transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width:18px; height:18px;
    border:1px solid {BORDER2}; background:{ENTRY}; }}
QCheckBox::indicator {{ border-radius:5px; }}
QRadioButton::indicator {{ border-radius:9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color:{ACC}; }}
QCheckBox::indicator:checked {{ background:{ACC}; border-color:{ACC}; image:none; }}
QRadioButton::indicator:checked {{ background:{ACC}; border-color:{ACC}; }}

QScrollArea {{ border:0; background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:5px; min-height:32px; }}
QScrollBar::handle:vertical:hover {{ background:{BORDER2}; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{BORDER}; border-radius:5px; min-width:32px; }}
QScrollBar::handle:horizontal:hover {{ background:{BORDER2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

QPlainTextEdit#log {{ font-family:'JetBrains Mono','Menlo','Consolas',monospace; font-size:12px;
    color:#a7f3d0; background:#070d18; border:1px solid {BORDER}; border-radius:10px; }}
"""


def _tok(s):
    """Token mã (bất biến) hiển thị trong tab HƯỚNG DẪN bằng rich-text."""
    return "<code style='color:%s; font-family:Menlo,Consolas,monospace;'>%s</code>" % (ACC, s)


# ============================== I18N — BẢNG DỊCH GIAO DIỆN ==============================
# Mọi chuỗi UI tĩnh nằm ở đây dưới dạng {key: {'vi':..., 'en':...}}. MainWindow.t(key, *args)
# trả chuỗi theo ngôn ngữ hiện tại (fallback 'vi', rồi key). Chuỗi có %s/%d -> gọi kèm args.
# Log nội bộ do engine phát (engine.py) vẫn là tiếng Việt — ngoài phạm vi i18n của UI.
TR = {
    # -- header / chung --
    'app_subtitle': {'vi': 'Dịch file KEY=text game EN→VI bằng AI   •   đa luồng   •   OpenAI / Anthropic',
                     'en': 'Translate KEY=text game files EN→VI with AI   •   multithreaded   •   OpenAI / Anthropic'},
    'lang_label': {'vi': 'Ngôn ngữ', 'en': 'Language'},
    # -- nhãn tab --
    'tab_api': {'vi': 'API', 'en': 'API'},
    'tab_prompt': {'vi': 'PROMPT HỆ THỐNG', 'en': 'SYSTEM PROMPT'},
    'tab_translate': {'vi': 'DỊCH', 'en': 'TRANSLATE'},
    'tab_preview': {'vi': 'XEM TRƯỚC', 'en': 'PREVIEW'},
    'tab_guide': {'vi': 'HƯỚNG DẪN', 'en': 'GUIDE'},
    # -- tab API --
    'api_format': {'vi': 'Định dạng API:', 'en': 'API format:'},
    'base_url': {'vi': 'Base URL:', 'en': 'Base URL:'},
    'base_tip': {'vi': 'Chỉ cần điền DOMAIN, vd: https://chat.trollllm.xyz\n'
                       'Tool tự thêm /v1/chat/completions (OpenAI) hoặc /v1/messages (Anthropic).\n'
                       'Dư dấu / hoặc sẵn /v1 đều được.',
                 'en': 'Just enter the DOMAIN, e.g. https://chat.trollllm.xyz\n'
                       'The tool adds /v1/chat/completions (OpenAI) or /v1/messages (Anthropic).\n'
                       'Trailing / or an existing /v1 are both fine.'},
    'api_keys_label': {'vi': 'API keys\n(mỗi dòng 1 key):', 'en': 'API keys\n(one per line):'},
    'keys_ph': {'vi': 'Dán API key, mỗi dòng 1 key (xoay vòng khi nhiều key)...',
                'en': 'Paste API keys, one per line (rotated when multiple)...'},
    'model_label': {'vi': 'Model:', 'en': 'Model:'},
    'model_default_label': {'vi': 'Model mặc định:', 'en': 'Default model:'},
    'model_prompt_label': {'vi': 'Model tạo prompt:', 'en': 'Prompt model:'},
    'model_translate_label': {'vi': 'Model dịch:', 'en': 'Translate model:'},
    'model_default_item': {'vi': '(Theo mặc định)', 'en': '(Default)'},
    'model_sel_tip': {'vi': 'Để "(Theo mặc định)" sẽ dùng Model mặc định ở tab API. '
                            'Chọn model cụ thể nếu muốn tab này dùng model khác.',
                      'en': 'Keep "(Default)" to use the Default model from the API tab. '
                            'Pick a specific model to override it for this tab.'},
    'model_ph': {'vi': 'Chọn từ danh sách hoặc gõ tên model...',
                 'en': 'Pick from the list or type a model name...'},
    'btn_fetch_models': {'vi': 'Lấy danh sách model', 'en': 'Fetch model list'},
    'auto_switch': {'vi': 'Tự động đổi sang model khác khi hết quota / lỗi (mặc định: CHỈ dùng model đã chọn)',
                    'en': 'Auto-switch to another model on quota / error (default: ONLY use the selected model)'},
    'auto_switch_tip': {'vi': 'Tắt: chỉ dịch bằng đúng model đã chọn; hết quota thì chờ rồi thử lại cùng model.\n'
                              'Bật: khi model chính lỗi/hết quota, tự xoay sang các model khác trong danh sách.',
                        'en': 'Off: translate only with the selected model; on quota it waits and retries the same model.\n'
                              'On: when the main model errors/runs out, auto-rotate to other models in the list.'},
    'send_temp_tip': {'vi': "Bỏ tích nếu model KHÔNG nhận tham số 'temperature' "
                            "(các model suy luận như gpt-5 / codex / o-series) — tool sẽ không gửi 'temperature'.",
                      'en': "Uncheck if the model does NOT accept 'temperature' "
                            "(reasoning models like gpt-5 / codex / o-series) — the tool won't send 'temperature'."},
    'timeout_label': {'vi': 'timeout (giây):', 'en': 'timeout (sec):'},
    'workers_label': {'vi': 'Số luồng:', 'en': 'Threads:'},
    'lines_label': {'vi': 'Dòng/lô:', 'en': 'Lines/batch:'},
    'btn_test': {'vi': 'Kiểm tra kết nối', 'en': 'Test connection'},
    'btn_save_cfg': {'vi': 'Lưu cấu hình', 'en': 'Save config'},
    'context_1m': {'vi': 'Context 1M (Claude beta)', 'en': 'Context 1M (Claude beta)'},
    'context_1m_tip': {'vi': 'Gửi header anthropic-beta: context-1m-2025-08-07 để mở context window 1 triệu token. '
                             'CHỈ cần cho Claude Sonnet 4 (cũ); các model mới (Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5) '
                             'ĐÃ có 1M sẵn theo mặc định, không cần bật. Muốn tận dụng cửa sổ lớn thì tăng "dòng/lô". '
                             'Một số router có thể từ chối header beta -> nếu gặp lỗi 400 thì bỏ tích.',
                       'en': 'Send header anthropic-beta: context-1m-2025-08-07 to unlock the 1M-token context window. '
                             'Only needed for Claude Sonnet 4 (legacy); newer models (Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5) '
                             'already have 1M by default. To actually use the larger window, raise "lines/batch". '
                             'Some routers may reject the beta header -> untick if you hit a 400 error.'},
    'debug_console': {'vi': 'Debug: in lỗi API ra console', 'en': 'Debug: print API errors to console'},
    'debug_tip': {'vi': 'Khi BẬT: mỗi lần gọi API lỗi (HTTP 4xx/5xx, JSON hỏng, sai cấu trúc...) sẽ in '
                        'URL + mã lỗi + NỘI DUNG API trả về ra console (terminal chạy app). KHÔNG in API key.',
                  'en': 'When ON: each failed API call (HTTP 4xx/5xx, broken JSON, bad shape...) prints the '
                        'URL + status + the API RESPONSE body to the console (the terminal running the app). API key is never printed.'},
    'st_saved_cfg': {'vi': 'Đã lưu config.json', 'en': 'Saved config.json'},
    'st_fetching_models': {'vi': 'Đang lấy model...', 'en': 'Fetching models...'},
    'st_models_fail': {'vi': 'Không lấy được danh sách model (Anthropic không hỗ trợ /models).',
                       'en': 'Could not fetch models (Anthropic has no /models).'},
    'st_models_ok': {'vi': 'Đã nạp %d model.', 'en': 'Loaded %d models.'},
    'st_testing': {'vi': 'Đang kiểm tra kết nối...', 'en': 'Testing connection...'},
    'st_err': {'vi': 'Lỗi: %s', 'en': 'Error: %s'},
    'st_conn_ok': {'vi': 'Kết nối OK: ', 'en': 'Connected: '},
    'st_conn_no': {'vi': 'Chưa được: ', 'en': 'Failed: '},
    # -- tab PROMPT --
    'game_name': {'vi': 'Tên game:', 'en': 'Game name:'},
    'game_ph': {'vi': 'vd: Control, Elden Ring, SAROS...', 'en': 'e.g. Control, Elden Ring, SAROS...'},
    'eng_file': {'vi': 'File text tiếng Anh:', 'en': 'English text file:'},
    'btn_browse': {'vi': 'Chọn…', 'en': 'Browse…'},
    'genre_tone': {'vi': 'Thể loại / tone:', 'en': 'Genre / tone:'},
    'extra_note': {'vi': 'Ghi chú thêm:', 'en': 'Extra notes:'},
    'note_ph': {'vi': 'vd: nhân vật chính tên X, xưng "tôi"...',
                'en': 'e.g. protagonist named X, uses first person...'},
    'btn_gen': {'vi': 'Tạo system prompt', 'en': 'Generate system prompt'},
    'btn_gen_running': {'vi': 'Đang tạo...', 'en': 'Generating...'},
    'btn_save_prompt': {'vi': 'Lưu prompt', 'en': 'Save prompt'},
    'btn_load_prompt': {'vi': 'Tải prompt', 'en': 'Load prompt'},
    'btn_clear': {'vi': 'Xóa', 'en': 'Clear'},
    'prompt_hint': {'vi': 'System prompt (sửa tay được — có nội dung sẽ dùng khi dịch, rỗng thì dùng luật mặc định):',
                    'en': 'System prompt (editable — used when filled; default rules when empty):'},
    'dlg_need_key_prompt': {'vi': 'Cấu hình API key ở tab API trước.',
                            'en': 'Configure an API key in the API tab first.'},
    'dlg_missing_file_t': {'vi': 'Thiếu file', 'en': 'Missing file'},
    'dlg_missing_file_m': {'vi': 'Chọn File text tiếng Anh hợp lệ.', 'en': 'Pick a valid English text file.'},
    'dlg_empty_file_t': {'vi': 'File rỗng', 'en': 'Empty file'},
    'dlg_empty_file_m': {'vi': 'File không có dòng ID=NỘI_DUNG để phân tích.',
                         'en': 'File has no ID=VALUE lines to analyze.'},
    'log_gen_prompt': {'vi': 'Đang nhờ %s viết system prompt cho "%s"...',
                       'en': 'Asking %s to write a system prompt for "%s"...'},
    'game_unnamed': {'vi': '(chưa đặt tên)', 'en': '(unnamed)'},
    'dlg_gen_fail_t': {'vi': 'Lỗi tạo prompt', 'en': 'Prompt generation error'},
    'log_gen_fail': {'vi': 'Tạo prompt thất bại: %s', 'en': 'Prompt generation failed: %s'},
    'gen_too_many_tokens': {'vi': 'Vượt giới hạn token khi tạo prompt. Tool chỉ gửi một MẪU nhỏ của file, '
                                  'nên thường do "max_tokens" ở tab API đặt quá lớn — hãy GIẢM max_tokens (vd 8192) rồi thử lại.',
                            'en': 'Token limit exceeded while generating the prompt. The tool only sends a small SAMPLE of the file, '
                                  'so this is usually because "max_tokens" in the API tab is too large — LOWER it (e.g. 8192) and retry.'},
    'sample_tok_info': {'vi': 'File mẫu: ≈ %s token  •  %s dòng cần dịch  •  %s ký tự   —   khi Tạo prompt chỉ gửi mẫu ≈ %s token',
                        'en': 'Sample file: ≈ %s tokens  •  %s translatable lines  •  %s chars   —   generating sends only a ≈ %s-token sample'},
    'gen_truncated_warn': {'vi': 'CẢNH BÁO: system prompt vừa tạo có thể bị CẮT NGANG do chạm trần output. '
                                 'Hãy TĂNG "max_tokens" ở tab API rồi bấm Tạo lại để có prompt đầy đủ.',
                           'en': 'WARNING: the generated system prompt may be CUT OFF (hit the output limit). '
                                 'Increase "max_tokens" in the API tab and Generate again for the full prompt.'},
    'log_gen_ok': {'vi': 'Đã tạo system prompt. Xem/sửa rồi bấm Lưu prompt.',
                   'en': 'System prompt generated. Review/edit then Save prompt.'},
    'dlg_saved_t': {'vi': 'Đã lưu', 'en': 'Saved'},
    'dlg_prompt_saved_m': {'vi': 'System prompt đã lưu:\n%s', 'en': 'System prompt saved:\n%s'},
    'fd_load_prompt': {'vi': 'Tải prompt', 'en': 'Load prompt'},
    # -- tab DỊCH --
    'tr_mode': {'vi': 'Chế độ:', 'en': 'Mode:'},
    'mode_file': {'vi': 'File đơn', 'en': 'Single file'},
    'mode_folder': {'vi': 'Cả thư mục', 'en': 'Whole folder'},
    'src_file': {'vi': 'File ENG gốc:', 'en': 'Source ENG file:'},
    'out_file': {'vi': 'File dịch (kết quả):', 'en': 'Output file (result):'},
    'src_folder': {'vi': 'Thư mục nguồn:', 'en': 'Source folder:'},
    'out_folder': {'vi': 'Thư mục kết quả:', 'en': 'Output folder:'},
    'ext_label': {'vi': 'Đuôi file:', 'en': 'Extensions:'},
    'ext_ph': {'vi': 'vd: .txt .json  (để trống = mọi file)', 'en': 'e.g. .txt .json  (empty = all files)'},
    'ext_tip': {'vi': 'Chỉ dịch file có đuôi này (cách nhau bởi dấu cách hoặc phẩy). '
                      'Để TRỐNG = dịch mọi file trong thư mục (đệ quy cả thư mục con).',
                'en': 'Only translate files with these extensions (space/comma separated). '
                      'Leave EMPTY = translate every file in the folder (recursively).'},
    'ext_all': {'vi': 'tất cả', 'en': 'all'},
    'dlg_no_src_folder': {'vi': 'Chưa chọn Thư mục nguồn hợp lệ.', 'en': 'No valid source folder selected.'},
    'dlg_no_out_folder': {'vi': 'Chưa chọn Thư mục kết quả.', 'en': 'No output folder selected.'},
    'fd_pick_folder': {'vi': 'Chọn thư mục', 'en': 'Select folder'},
    'folder_none': {'vi': 'Không tìm thấy file nào khớp đuôi trong thư mục.',
                    'en': 'No files matching the extensions in this folder.'},
    'folder_overview': {'vi': 'Tìm thấy %d file — %d file đã có kết quả ở thư mục đích.',
                        'en': 'Found %d files — %d already have output in the target folder.'},
    'folder_starting': {'vi': 'Đang quét thư mục...', 'en': 'Scanning folder...'},
    'folder_init': {'vi': 'Thư mục: %d file (đuôi: %s)', 'en': 'Folder: %d files (ext: %s)'},
    'folder_progress': {'vi': 'File %d/%d: %s', 'en': 'File %d/%d: %s'},
    'btn_start': {'vi': 'BẮT ĐẦU DỊCH', 'en': 'START TRANSLATING'},
    'btn_stop': {'vi': 'DỪNG', 'en': 'STOP'},
    'card_translated': {'vi': 'Đã dịch', 'en': 'Translated'},
    'card_speed': {'vi': 'Tốc độ', 'en': 'Speed'},
    'card_eta': {'vi': 'ETA', 'en': 'ETA'},
    'card_err': {'vi': 'Lỗi', 'en': 'Errors'},
    'batch_progress': {'vi': 'Tiến độ từng lô', 'en': 'Per-batch progress'},
    'tbl_thread': {'vi': 'Luồng', 'en': 'Thread'},
    'tbl_batch': {'vi': 'Lô', 'en': 'Batch'},
    'tbl_model': {'vi': 'Model', 'en': 'Model'},
    'tbl_status': {'vi': 'Trạng thái', 'en': 'Status'},
    'stt_queued': {'vi': 'chờ', 'en': 'queued'},
    'stt_running': {'vi': 'đang dịch', 'en': 'translating'},
    'stt_done': {'vi': 'xong', 'en': 'done'},
    'stt_retry': {'vi': 'thử lại', 'en': 'retry'},
    'stt_error': {'vi': 'lỗi', 'en': 'error'},
    'wk_translating': {'vi': 'đang dịch', 'en': 'translating'},
    'wk_waiting': {'vi': 'chờ key', 'en': 'waiting key'},
    'wk_idle': {'vi': 'rảnh', 'en': 'idle'},
    'sub_lines_min': {'vi': 'dòng/phút', 'en': 'lines/min'},
    'sub_left': {'vi': 'còn lại', 'en': 'left'},
    'sub_retry': {'vi': '%d retry', 'en': '%d retries'},
    'tip_batch': {'vi': 'Lô %d — %s', 'en': 'Batch %d — %s'},
    'tip_lines': {'vi': '%d dòng', 'en': '%d lines'},
    'tip_err': {'vi': 'lỗi: %s', 'en': 'error: %s'},
    'log_batch_init': {'vi': '— %s: %d lô —', 'en': '— %s: %d batches —'},
    'dlg_no_src': {'vi': 'Chưa chọn File ENG gốc hợp lệ.', 'en': 'No valid source ENG file selected.'},
    'dlg_no_out': {'vi': 'Chưa chọn nơi lưu file dịch.', 'en': 'No output file selected.'},
    'dlg_no_key': {'vi': 'Chưa có API key (tab API).', 'en': 'No API key (API tab).'},
    'dlg_no_model': {'vi': 'Chưa chọn model (tab API).', 'en': 'No model selected (API tab).'},
    'use_prompt': {'vi': 'System prompt: %s', 'en': 'System prompt: %s'},
    'sp_custom': {'vi': 'tự sinh/sửa tay (%d ký tự)', 'en': 'custom/edited (%d chars)'},
    'sp_default': {'vi': 'luật mặc định', 'en': 'default rules'},
    'log_stopping': {'vi': 'Đang dừng... (đã lưu tới đây, mở lại sẽ chạy tiếp)',
                     'en': 'Stopping... (saved so far, reopen to continue)'},
    'resume_none': {'vi': 'Chưa có tiến độ đã lưu — sẽ dịch %d dòng.',
                    'en': 'No saved progress — will translate %d lines.'},
    'resume_done': {'vi': 'Đã dịch xong toàn bộ %d dòng (bấm Bắt đầu để kiểm/sửa lại).',
                    'en': 'All %d lines translated (press Start to recheck/fix).'},
    'resume_partial': {'vi': 'Tiến độ đã lưu: %d/%d dòng — bấm Bắt đầu sẽ DỊCH TIẾP %d dòng còn lại.',
                       'en': 'Saved progress: %d/%d lines — press Start to CONTINUE the remaining %d.'},
    'dlg_done_t': {'vi': 'Hoàn tất', 'en': 'Done'},
    # -- tab XEM TRƯỚC --
    'btn_refresh': {'vi': 'Làm mới', 'en': 'Refresh'},
    'search_ph': {'vi': 'Tìm trong key / tiếng Anh / tiếng Việt...',
                  'en': 'Search key / English / Vietnamese...'},
    'only_pending': {'vi': 'Chỉ hiện chưa dịch / nghi lỗi', 'en': 'Show only untranslated / suspicious'},
    'pv_not_loaded': {'vi': 'Chưa tải. Bấm "Làm mới" (lấy từ File ENG gốc + File dịch ở tab DỊCH).',
                      'en': 'Not loaded. Press "Refresh" (uses the Source + Output files from the TRANSLATE tab).'},
    'pv_no_src': {'vi': 'Chưa chọn File ENG gốc hợp lệ ở tab DỊCH.',
                  'en': 'No valid source ENG file in the TRANSLATE tab.'},
    'pv_loading': {'vi': 'Đang tải bản xem trước...', 'en': 'Loading preview...'},
    'pv_load_err': {'vi': 'Lỗi tải xem trước: %s', 'en': 'Preview load error: %s'},
    'pv_summary': {'vi': 'Tổng %d dòng  |  đã dịch %d  |  chưa %d  |  nghi lỗi %d  |  vượt byte %d',
                   'en': 'Total %d lines  |  translated %d  |  pending %d  |  suspicious %d  |  over-byte %d'},
    'pv_filtered': {'vi': 'Hiển thị %d/%d dòng (đang lọc)', 'en': 'Showing %d/%d lines (filtered)'},
    'col_key': {'vi': 'Key', 'en': 'Key'},
    'col_en': {'vi': 'Tiếng Anh', 'en': 'English'},
    'col_vi': {'vi': 'Tiếng Việt', 'en': 'Vietnamese'},
    'col_byte_en': {'vi': 'Byte EN', 'en': 'EN bytes'},
    'col_byte_vi': {'vi': 'Byte VI', 'en': 'VI bytes'},
    'only_over': {'vi': 'Chỉ hiện vượt byte', 'en': 'Show only over-byte'},
    'byte_limit': {'vi': 'Giới hạn byte ≤ bản gốc', 'en': 'Limit bytes ≤ source'},
    'byte_limit_tip': {'vi': 'Khi BẬT: ép số byte UTF-8 của bản dịch KHÔNG vượt câu gốc EN (buffer game). '
                             'Gửi ngân sách max_bytes cho AI và DỊCH LẠI dòng còn vượt qua các vòng tự-sửa. '
                             'Khi TẮT: chỉ XEM đối chiếu byte + tô đỏ cảnh báo ở tab Xem trước (không dịch lại). '
                             'Lưu ý: tiếng Việt có dấu tốn 2-3 byte/ký tự nên nhiều dòng có thể KHÔNG thể vừa.',
                       'en': 'When ON: force the translation UTF-8 byte count NOT to exceed the source EN line '
                             '(game buffer). Sends a max_bytes budget to the AI and RE-TRANSLATES over-byte lines '
                             'across self-fix rounds. When OFF: only compare bytes + red warning in the Preview tab '
                             '(no re-translation). Note: Vietnamese diacritics cost 2-3 bytes/char so some lines may '
                             'be impossible to fit.'},
    # -- dialog / file dialog chung --
    'dlg_err': {'vi': 'Lỗi', 'en': 'Error'},
    'dlg_cant_save_cfg': {'vi': 'Không lưu được config: %s', 'en': 'Could not save config: %s'},
    'dlg_missing_key_t': {'vi': 'Thiếu key', 'en': 'Missing key'},
    'dlg_missing_key_m': {'vi': 'Hãy dán ít nhất 1 API key.', 'en': 'Please paste at least one API key.'},
    'dlg_missing_model_t': {'vi': 'Thiếu model', 'en': 'Missing model'},
    'dlg_missing_model_m': {'vi': 'Hãy chọn/nhập model.', 'en': 'Please select or type a model.'},
    'dlg_busy_t': {'vi': 'Đang dịch', 'en': 'Busy'},
    'dlg_busy_m': {'vi': 'Đang dịch — hãy dừng trước khi đổi ngôn ngữ.',
                   'en': 'Translation is running — stop it before switching language.'},
    'fd_save': {'vi': 'Lưu', 'en': 'Save'},
    'fd_pick': {'vi': 'Chọn', 'en': 'Select'},
    'fd_pick_eng': {'vi': 'Chọn file ENG', 'en': 'Select ENG file'},
}

# Nội dung tab HƯỚNG DẪN theo ngôn ngữ. Dựng lại khi đổi ngôn ngữ (rebuild central).
# Màu trạng thái dùng chung cho 2 ngôn ngữ; chỉ tên + mô tả là song ngữ.
STATE_GUIDE_COLORS = [STATE_COLOR[ST_QUEUED].name(), YEL, GREEN, ORANGE, RED]

def _guide_data(lang):
    en = (lang == 'en')
    if en:
        steps = [
            ('Configure API  —  API tab', [
                "Pick the format %s (e.g. trolllm) or %s." % (_tok('OpenAI-compatible'), _tok('Anthropic')),
                "Fill in <b>Base URL</b>: just the domain like %s — the tool adds %s." % (_tok('chat.trollllm.xyz'), _tok('/v1/…')),
                "Paste <b>API keys</b>, one per line (multiple keys rotate automatically).",
                "Pick a <b>Model</b> (OpenAI: click <b>Fetch model list</b>), then <b>Test connection</b>.",
                "Click <b>Save config</b> to remember it next time.",
            ]),
            ('Generate System Prompt  —  SYSTEM PROMPT tab', [
                "Enter the <b>Game name</b> and pick an <b>English text file</b> as a sample.",
                "The tool shows the file's <b>estimated tokens</b> below; only a small <b>sample</b> is sent, so a big file won't blow the token limit (if it still does, <b>lower max_tokens</b>).",
                "Choose <b>genre / tone</b>, click <b>Generate system prompt</b> — the AI writes context, glossary, voice, rules.",
                "Edit freely, then click <b>Save prompt</b>.",
                "Leave it empty → the tool uses the <b>built-in default rules</b>.",
            ]),
            ('Pick files & start  —  TRANSLATE tab', [
                "Pick the <b>Source ENG file</b>; the tool suggests an <b>Output file</b> name (adds _VI).",
                "<b>Whole folder</b> mode: pick a source folder + optional <b>extensions</b> (e.g. .txt .json; empty = all) → it translates every matching file (recursively) into a parallel <b>_vi</b> folder, keeping the tree.",
                "Click <b>START TRANSLATING</b>. You can press <b>STOP</b> anytime.",
                "It <b>saves as it goes</b> — close and reopen, press Start to <b>continue</b>.",
            ]),
            ('Track progress  —  TRANSLATE tab', [
                "Four stat cards: <b>Translated</b>, <b>Speed</b>, <b>ETA</b> (time left), <b>Errors</b>.",
                "<b>Color grid</b>: each cell is a batch — color shows status (see table below). Hover for details.",
                "Live <b>thread</b> table and real-time <b>log</b> below.",
            ]),
            ('Preview & review  —  PREVIEW tab', [
                "Side-by-side <b>Key / English / Vietnamese</b> — opens instantly even for tens of thousands of lines.",
                "<b>Untranslated</b> rows are amber, <b>suspicious</b> rows are red.",
                "Use <b>search</b> + the <b>“Show only untranslated / suspicious”</b> filter to review fast.",
            ]),
        ]
        inv_rows = [
            (['{var}', '{0}'], 'Content variables — the game replaces them with the player name, counts, key bindings…'),
            (['<tag>', '</tag>'], 'Formatting / color / effect tags shown in-game.'),
            (['[REDACTED]', '[OK]'], 'UPPERCASE tokens in brackets — control codes, keep as-is.'),
            (['\\n', '\\r'], 'Line-break characters — the count must match the original exactly.'),
        ]
        states = [('Queued', 'Batch is waiting its turn.'),
                  ('Translating', 'A thread is calling the AI for this batch.'),
                  ('Done', 'Batch translated and written to the output file.'),
                  ('Retry', 'Temporary error or quota — auto-rotates key/model and retries.'),
                  ('Error', 'Batch failed after many tries (rare) — rerun to continue.')]
        trouble_heads = ['Situation', 'Cause', 'What to do']
        trouble_rows = [
            ['<b>Out of quota / 429</b>', 'Key called too many times in a short window.',
             'The tool waits and rotates key/model. Paste <b>more keys</b> in the API tab to go faster.'],
            ['<b>Dead key / 401, 403</b>', 'API key is wrong or revoked.',
             'The tool drops that key. Check it and paste a new key in the API tab.'],
            ['<b>Transient / 502, timeout</b>', 'Server busy or flaky network.',
             'The tool retries after a few seconds — usually nothing to do.'],
            ['<b>Closed mid-run</b>', 'App closed, power loss, or you pressed Stop.',
             'Reopen, pick the same two files, press <b>Start</b> — it continues where it left off.'],
            ['<b>{var} / tag mismatch</b>', 'AI got a placeholder wrong while translating.',
             'The tool detects it and <b>re-translates</b> those lines (self-check loop).'],
        ]
        tips = [
            'Paste <b>multiple API keys</b> → the tool rotates them in parallel, faster and dodges rate-limits.',
            'By default it uses only the <b>selected model</b>; enable <b>“Auto-switch model”</b> in the API tab to jump to others when stuck.',
            '<b>The output file is the source of truth</b>: progress is read from the real file — delete it to re-translate cleanly.',
            'Results are written <b>atomically</b> after each batch — a sudden shutdown won\'t corrupt the file.',
            'Raise <b>Threads</b> (API tab) to go faster if the API allows; lower it if you hit rate-limits often.',
        ]
        ex_intro = 'Example — keep every invariant when translating:'
        data = {
            'banner_title': 'Quick start guide',
            'banner_html': ('A tool that translates game localization files in <b>KEY=value</b> format from '
                            '<b>English to Vietnamese</b> with AI — auto-batching, <b>multithreaded</b>, '
                            'self-checks &amp; fixes placeholders, and <b>remembers progress</b> to resume after closing.'),
            'h_process': 'The 5-step workflow', 'h_invariants': 'Invariants — AI must KEEP as-is (do not translate)',
            'h_states': 'Per-batch status colors (TRANSLATE tab)', 'h_trouble': 'Common troubleshooting',
            'h_tips': 'Tips & handy behavior',
        }
    else:
        steps = [
            ('Cấu hình API  —  tab API', [
                "Chọn định dạng %s (vd trolllm) hoặc %s." % (_tok('OpenAI-compatible'), _tok('Anthropic')),
                "Điền <b>Base URL</b>: chỉ cần domain như %s — tool tự thêm %s." % (_tok('chat.trollllm.xyz'), _tok('/v1/…')),
                "Dán <b>API key</b>, mỗi dòng 1 key (nhiều key sẽ tự xoay vòng).",
                "Chọn <b>Model</b> (OpenAI bấm <b>Lấy danh sách model</b>), rồi <b>Kiểm tra kết nối</b>.",
                "Bấm <b>Lưu cấu hình</b> để ghi nhớ cho lần sau.",
            ]),
            ('Tạo System Prompt  —  tab PROMPT HỆ THỐNG', [
                "Nhập <b>Tên game</b> và chọn <b>File text tiếng Anh</b> làm mẫu.",
                "Tool hiện <b>ước lượng token</b> của file phía dưới; chỉ gửi một <b>mẫu nhỏ</b> nên file lớn không vượt giới hạn token (nếu vẫn lỗi, hãy <b>giảm max_tokens</b>).",
                "Chọn <b>thể loại / tone</b>, bấm <b>Tạo system prompt</b> — AI tự viết bối cảnh, glossary, văn phong, quy tắc.",
                "Sửa tay tùy ý rồi bấm <b>Lưu prompt</b>.",
                "Để trống ô prompt → tool dùng <b>luật dịch mặc định</b> sẵn có.",
            ]),
            ('Chọn file & bắt đầu dịch  —  tab DỊCH', [
                "Chọn <b>File ENG gốc</b>; tool tự gợi ý tên <b>File dịch</b> (thêm hậu tố _VI).",
                "Chế độ <b>Cả thư mục</b>: chọn thư mục nguồn + <b>đuôi file</b> (vd .txt .json; trống = mọi file) → dịch mọi file khớp (đệ quy cả thư mục con) sang thư mục song song <b>_vi</b>, giữ nguyên cây thư mục.",
                "Bấm <b>BẮT ĐẦU DỊCH</b>. Có thể bấm <b>DỪNG</b> bất cứ lúc nào.",
                "Dịch tới đâu <b>lưu tới đó</b> — tắt rồi mở lại bấm Bắt đầu sẽ <b>chạy tiếp</b>.",
            ]),
            ('Theo dõi tiến độ  —  tab DỊCH', [
                "4 thẻ thống kê: <b>Đã dịch</b>, <b>Tốc độ</b>, <b>ETA</b> (thời gian còn lại), <b>Lỗi</b>.",
                "<b>Lưới ô màu</b>: mỗi ô là 1 lô — màu cho biết trạng thái (xem bảng bên dưới). Rê chuột để xem chi tiết.",
                "Bảng <b>luồng</b> đang chạy và <b>log</b> thời gian thực ở phía dưới.",
            ]),
            ('Xem trước & soát lỗi  —  tab XEM TRƯỚC', [
                "Bảng đối chiếu <b>Key / Tiếng Anh / Tiếng Việt</b> — mở tức thì kể cả file vài chục nghìn dòng.",
                "Dòng <b>chưa dịch</b> tô vàng, dòng <b>nghi lỗi</b> tô đỏ để dễ thấy.",
                "Dùng ô <b>tìm kiếm</b> + lọc <b>“Chỉ hiện chưa dịch / nghi lỗi”</b> để soát nhanh.",
            ]),
        ]
        inv_rows = [
            (['{biến}', '{0}'], 'Biến nội dung — game sẽ thay bằng tên người chơi, số lượng, phím bấm…'),
            (['<thẻ>', '</thẻ>'], 'Thẻ định dạng / màu chữ / hiệu ứng hiển thị trong game.'),
            (['[REDACTED]', '[OK]'], 'Token chữ HOA trong ngoặc vuông — mã điều khiển, giữ nguyên.'),
            (['\\n', '\\r'], 'Ký tự xuống dòng — số lượng phải khớp đúng bản gốc.'),
        ]
        states = [('Chờ', 'Lô đang xếp hàng, chưa tới lượt xử lý.'),
                  ('Đang dịch', 'Một luồng đang gọi AI dịch lô này.'),
                  ('Xong', 'Lô đã dịch xong và đã ghi ra file kết quả.'),
                  ('Thử lại', 'Gặp lỗi tạm hoặc hết quota — tự đổi key/model rồi thử lại.'),
                  ('Lỗi', 'Lô lỗi sau nhiều lần thử (hiếm) — chạy lại sẽ dịch tiếp.')]
        trouble_heads = ['Tình huống', 'Nguyên nhân', 'Cách xử lý']
        trouble_rows = [
            ['<b>Hết quota / 429</b>', 'Key gọi quá nhiều trong thời gian ngắn.',
             'Tool tự chờ rồi xoay key/model. Dán <b>nhiều key</b> ở tab API để nhanh hơn.'],
            ['<b>Key chết / 401, 403</b>', 'API key sai hoặc đã bị thu hồi.',
             'Tool tự loại key đó. Kiểm tra lại và dán key mới ở tab API.'],
            ['<b>Lỗi tạm / 502, timeout</b>', 'Server bận hoặc mạng chập chờn.',
             'Tool tự thử lại sau vài giây — thường không cần làm gì.'],
            ['<b>Lỡ tắt giữa chừng</b>', 'Đóng app, mất điện, hoặc bấm Dừng.',
             'Mở lại, chọn đúng 2 file cũ, bấm <b>Bắt đầu</b> — chạy tiếp từ chỗ dở.'],
            ['<b>Lệch {biến} / thẻ</b>', 'AI làm sai placeholder khi dịch.',
             'Tool tự phát hiện và <b>dịch lại</b> đúng các dòng đó (vòng tự kiểm).'],
        ]
        tips = [
            'Dán <b>nhiều API key</b> → tool xoay vòng song song, dịch nhanh và né rate-limit tốt hơn.',
            'Mặc định chỉ dùng <b>model đã chọn</b>; bật <b>“Tự đổi model”</b> ở tab API để nhảy sang model khác khi nghẽn.',
            '<b>File kết quả là nguồn chân lý</b>: tiến độ tính theo nội dung thật trong file — xóa file là dịch lại từ đầu, không sợ lẫn.',
            'Kết quả ghi <b>an toàn (atomic)</b> sau mỗi lô — tắt đột ngột cũng không hỏng file.',
            'Tăng <b>Số luồng</b> (tab API) để dịch nhanh hơn nếu API cho phép; giảm xuống nếu hay bị rate-limit.',
        ]
        ex_intro = 'Ví dụ — giữ nguyên mọi bất biến khi dịch:'
        data = {
            'banner_title': 'Hướng dẫn sử dụng nhanh',
            'banner_html': ('Công cụ dịch file localization game dạng <b>KEY=nội dung</b> từ '
                            '<b>tiếng Anh sang tiếng Việt</b> bằng AI — tự chia lô, dịch <b>đa luồng</b>, '
                            'tự kiểm &amp; sửa lỗi placeholder, và <b>nhớ tiến độ</b> để dịch tiếp khi tắt giữa chừng.'),
            'h_process': 'Quy trình 5 bước', 'h_invariants': 'Bất biến — AI phải giữ NGUYÊN (không dịch)',
            'h_states': 'Màu trạng thái từng lô (tab DỊCH)', 'h_trouble': 'Xử lý sự cố thường gặp',
            'h_tips': 'Mẹo & cơ chế hữu ích',
        }
    # ví dụ EN→VI (dùng chung, chỉ câu dẫn được dịch theo ngôn ngữ)
    t_var = _tok('{0}'); t_tag = _tok('&lt;b&gt;{name}&lt;/b&gt;'); t_nl = _tok('\\n')
    data['inv_example'] = (
        ex_intro + '<br>'
        + ("<span style='color:%s'>EN</span>&nbsp;&nbsp; " % DIM)
        + 'Press ' + t_var + ' to talk to ' + t_tag + t_nl + 'Good luck!<br>'
        + ("<span style='color:%s'>VI</span>&nbsp;&nbsp; " % GREEN)
        + 'Nhấn ' + t_var + ' để nói chuyện với ' + t_tag + t_nl + 'Chúc may mắn!')
    data['steps'] = steps; data['inv_rows'] = inv_rows; data['states'] = states
    data['trouble_heads'] = trouble_heads; data['trouble_rows'] = trouble_rows; data['tips'] = tips
    return data


# ============================== ENGINE BRIDGE / THREADS ==============================
class EngineBridge(QObject):
    """Bọc callback emit(evt) của engine -> pyqtSignal (an toàn cross-thread)."""
    sig_progress   = pyqtSignal(dict)
    sig_batch_init = pyqtSignal(dict)
    sig_batch      = pyqtSignal(dict)
    sig_worker     = pyqtSignal(dict)
    sig_log        = pyqtSignal(str)
    sig_stats      = pyqtSignal(dict)
    sig_finished   = pyqtSignal(dict)
    sig_folder_init = pyqtSignal(dict)
    sig_folder_file = pyqtSignal(dict)

    def emit_event(self, evt):
        t = evt.get('type')
        if   t == 'progress':    self.sig_progress.emit(evt)
        elif t == 'batch_init':  self.sig_batch_init.emit(evt)
        elif t == 'batch':       self.sig_batch.emit(evt)
        elif t == 'worker':      self.sig_worker.emit(evt)
        elif t == 'log':         self.sig_log.emit(evt.get('msg', ''))
        elif t == 'stats':       self.sig_stats.emit(evt)
        elif t == 'finished':    self.sig_finished.emit(evt)
        elif t == 'folder_init': self.sig_folder_init.emit(evt)
        elif t == 'folder_file': self.sig_folder_file.emit(evt)


class OrchestratorThread(QThread):
    def __init__(self, cfg, bridge, stop_event):
        super().__init__(); self.cfg = cfg; self.bridge = bridge; self.stop = stop_event
    def run(self):
        if self.cfg.get('mode') == 'folder':          # dịch cả thư mục (đa file)
            E.run_folder_translation(self.cfg, self.bridge.emit_event, self.stop)
        else:
            E.run_translation(self.cfg, self.bridge.emit_event, self.stop)


class FnThread(QThread):
    """Chạy 1 hàm nền, phát kết quả (hoặc Exception) qua signal done."""
    done = pyqtSignal(object)
    def __init__(self, fn): super().__init__(); self._fn = fn
    def run(self):
        try: self.done.emit(self._fn())
        except Exception as e: self.done.emit(e)


# ============================== WIDGET TRỰC QUAN HÓA ==============================
class BatchGridWidget(QWidget):
    """Lưới ô màu trạng thái từng lô (QPainter). Hover xem chi tiết."""
    CELL = 15; GAP = 4
    def __init__(self):
        super().__init__()
        self.states = []; self.meta = {}
        self.names = dict(STATE_NAME)      # tên trạng thái (đổi theo ngôn ngữ ở _tab_translate)
        self.tip = {'batch': 'Lô %d — %s', 'model': 'model: %s', 'lines': '%d dòng', 'err': 'lỗi: %s'}
        self.setMouseTracking(True)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def reset(self, n):
        self.states = [ST_QUEUED] * n; self.meta = {}
        self.setMinimumHeight(self._rows_height()); self.update()

    def set_state(self, bid, state, info=None):
        if 0 <= bid < len(self.states):
            self.states[bid] = state
            if info: self.meta[bid] = info
            self.update()

    def _cols(self):
        return max(1, (self.width() + self.GAP) // (self.CELL + self.GAP))

    def _rows_height(self):
        if not self.states: return 60
        rows = (len(self.states) + self._cols() - 1) // self._cols()
        return max(60, rows * (self.CELL + self.GAP) + 4)

    def resizeEvent(self, e):
        self.setMinimumHeight(self._rows_height()); super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        cols = self._cols()
        for i, stt in enumerate(self.states):
            r, c = divmod(i, cols)
            x = c * (self.CELL + self.GAP); y = r * (self.CELL + self.GAP)
            p.fillRect(QRect(x, y, self.CELL, self.CELL), STATE_COLOR.get(stt, QColor(BORDER)))
        p.end()

    def _hit(self, pos):
        cols = self._cols()
        c = pos.x() // (self.CELL + self.GAP); r = pos.y() // (self.CELL + self.GAP)
        if c >= cols: return -1
        bid = r * cols + c
        return bid if 0 <= bid < len(self.states) else -1

    def mouseMoveEvent(self, e):
        bid = self._hit(e.pos())
        if bid >= 0:
            info = self.meta.get(bid, {})
            txt = self.tip['batch'] % (bid + 1, self.names.get(self.states[bid], '?'))
            if info.get('model'): txt += '\n' + self.tip['model'] % info['model']
            if info.get('n_lines'): txt += '\n' + self.tip['lines'] % info['n_lines']
            if info.get('err'): txt += '\n' + self.tip['err'] % info['err']
            QToolTip.showText(e.globalPosition().toPoint(), txt, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(e)


class StatCard(QFrame):
    def __init__(self, title):
        super().__init__(); self.setObjectName('stat')
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(2)
        self.t = QLabel(title); self.t.setObjectName('muted')
        self.v = QLabel('—'); self.v.setStyleSheet('font-size:20px; font-weight:800;')
        self.s = QLabel(''); self.s.setObjectName('muted')
        lay.addWidget(self.t); lay.addWidget(self.v); lay.addWidget(self.s)
    def set(self, value, sub=''):
        self.v.setText(str(value)); self.s.setText(sub)


# ============================== MODEL ẢO HÓA CHO TAB XEM TRƯỚC ==============================
# QTableView + model ảo hóa: chỉ vẽ phần nhìn thấy -> mở tab tức thì kể cả vài chục nghìn dòng
# (QTableWidget tạo item cho MỌI ô sẽ làm đơ UI khi file lớn).
_PV_BRUSH = {1: QBrush(QColor('#33290f')), 2: QBrush(QColor('#3a1f29'))}   # chưa dịch / nghi lỗi
_PV_OVER = QBrush(QColor('#5a1d1d'))   # ô 'Byte VI' khi bản dịch VƯỢT byte gốc (đỏ đậm cảnh báo)

class PreviewModel(QAbstractTableModel):
    # row = (key, en, vi, status, en_bytes, vi_bytes) — thêm 2 cột so sánh byte
    HEAD = ['Key', 'Tiếng Anh', 'Tiếng Việt', 'Byte EN', 'Byte VI']
    CHUNK = 250                                       # số hàng nạp mỗi lần cuộn (lazy load)
    def __init__(self):
        super().__init__(); self._rows = []; self._loaded = 0   # _rows: toàn bộ; _loaded: số hàng đã lộ
        self.head = list(self.HEAD)                              # tiêu đề cột (đổi theo ngôn ngữ)
    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows; self._loaded = min(self.CHUNK, len(rows))
        self.endResetModel()
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._loaded   # chỉ lộ phần đã nạp
    def columnCount(self, parent=QModelIndex()):
        return 5
    # --- LAZY LOAD: cuộn tới cuối -> nạp thêm 1 chunk ---
    def canFetchMore(self, parent=QModelIndex()):
        return False if parent.isValid() else self._loaded < len(self._rows)
    def fetchMore(self, parent=QModelIndex()):
        if parent.isValid(): return
        add = min(self.CHUNK, len(self._rows) - self._loaded)
        if add <= 0: return
        self.beginInsertRows(QModelIndex(), self._loaded, self._loaded + add - 1)
        self._loaded += add
        self.endInsertRows()
    def load_all(self):
        """Lộ hết hàng (dùng khi lọc/tìm để kết quả đầy đủ)."""
        if self._loaded < len(self._rows):
            self.beginInsertRows(QModelIndex(), self._loaded, len(self._rows) - 1)
            self._loaded = len(self._rows)
            self.endInsertRows()
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        r = self._rows[index.row()]; col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if col == 3: return str(r[4])             # Byte EN
            if col == 4: return str(r[5])             # Byte VI
            return r[col]                             # key / en / vi
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (3, 4):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole:
            if col == 4 and r[5] > r[4] and r[2].strip() and r[2] != r[1]:
                return _PV_OVER                       # bản dịch vượt byte gốc -> tô đỏ ô Byte VI
            return _PV_BRUSH.get(r[3])
        return None
    def headerData(self, section, orient, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orient == Qt.Orientation.Horizontal:
            return self.head[section]
        return None

class PreviewFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__(); self.query = ''; self.only_pending = False; self.only_over = False
    def set_query(self, q):
        self.query = (q or '').strip().lower(); self.invalidateFilter()
    def set_only(self, b):
        self.only_pending = bool(b); self.invalidateFilter()
    def set_only_over(self, b):
        self.only_over = bool(b); self.invalidateFilter()
    def filterAcceptsRow(self, row, parent):
        rows = self.sourceModel()._rows
        if row >= len(rows): return False
        k, en, vi, status, en_b, vi_b = rows[row]
        if self.only_pending and status == 0: return False
        if self.only_over and not (vi.strip() and vi != en and vi_b > en_b): return False
        q = self.query
        if q and q not in k.lower() and q not in en.lower() and q not in vi.lower(): return False
        return True


# ============================== CỬA SỔ CHÍNH ==============================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('KeyValue Game Localization AI Translator  •  PS5VietHoa (Phước Lê & Mèo Mặt Căng)')
        self.resize(1040, 800)
        self.cfg = self._load_config()
        self.lang = self.cfg.get('lang', 'vi')
        if self.lang not in LANGS: self.lang = 'vi'
        self.bridge = EngineBridge(); self._wire_bridge()
        self.orch = None; self.stop_event = None
        self._threads = []
        self._log_buf = []; self._log_timer = QTimer(self); self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start(120)
        self._build_central()
        self._apply_config_to_ui()

    # ---------- i18n ----------
    def t(self, key, *args):
        """Chuỗi UI theo ngôn ngữ hiện tại (fallback 'vi' rồi key). Có %s/%d -> truyền args."""
        d = TR.get(key)
        s = (d.get(self.lang) or d.get('vi')) if d else key
        return (s % args) if args else s

    def _build_central(self):
        """Dựng header + 5 tab theo ngôn ngữ hiện tại. Gọi lại khi đổi ngôn ngữ."""
        central = QWidget()
        root = QVBoxLayout(central); root.setContentsMargins(12, 10, 12, 10); root.setSpacing(8)
        root.addWidget(self._header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_api(), self.t('tab_api'))
        self.tabs.addTab(self._tab_prompt(), self.t('tab_prompt'))
        self.tabs.addTab(self._tab_translate(), self.t('tab_translate'))
        self.tabs.addTab(self._tab_preview(), self.t('tab_preview'))
        self.tabs.addTab(self._tab_guide(), self.t('tab_guide'))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)        # thay central cũ (Qt tự huỷ widget cũ)

    def _on_lang_changed(self, idx):
        new = LANGS[idx] if 0 <= idx < len(LANGS) else 'vi'
        if new == self.lang: return
        if self.orch and self.orch.isRunning():        # đang dịch -> không rebuild, hoàn tác lựa chọn
            self.cb_lang.blockSignals(True); self.cb_lang.setCurrentIndex(LANGS.index(self.lang))
            self.cb_lang.blockSignals(False)
            QMessageBox.information(self, self.t('dlg_busy_t'), self.t('dlg_busy_m')); return
        self._set_lang(new)

    def _set_lang(self, new):
        snap = self._snapshot_ui()      # giữ lại mọi ô nhập trước khi dựng lại
        self.lang = new; self.cfg['lang'] = new
        self._persist_lang()
        self._build_central()
        self._restore_ui(snap)

    # ---------- header ----------
    def _header(self):
        f = QFrame(); f.setObjectName('appheader')
        f.setStyleSheet(
            'QFrame#appheader {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            ' stop:0 {card}, stop:1 {bg}); border:1px solid {bd}; border-radius:12px; }}'
            .format(card=CARD, bg=BG, bd=BORDER))
        lay = QHBoxLayout(f); lay.setContentsMargins(16, 12, 18, 12); lay.setSpacing(14)
        badge = QLabel('KV'); badge.setFixedSize(46, 46)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet('background:qlineargradient(x1:0,y1:0,x2:1,y2:1, '
                            'stop:0 %s, stop:1 %s); color:%s; font-size:19px; '
                            'font-weight:800; border-radius:12px;' % (ACC, GREEN, INK))
        lay.addWidget(badge)
        box = QVBoxLayout(); box.setSpacing(2)
        t = QLabel('KEYVALUE LOCALIZATION AI')
        t.setStyleSheet(f'color:{FG}; font-size:17px; font-weight:800;')
        s = QLabel(self.t('app_subtitle'))
        s.setStyleSheet(f'color:{MUTED}; font-size:12px;')
        box.addWidget(t); box.addWidget(s)
        lay.addLayout(box); lay.addStretch(1)
        # bộ chuyển ngôn ngữ
        lang_lab = QLabel(self.t('lang_label')); lang_lab.setStyleSheet(f'color:{MUTED}; font-size:11px;')
        self.cb_lang = QComboBox(); self.cb_lang.addItems(LANG_NAMES); self.cb_lang.setFixedWidth(132)
        self.cb_lang.setCurrentIndex(LANGS.index(self.lang))      # đặt trước khi connect -> không tự kích hoạt
        self.cb_lang.currentIndexChanged.connect(self._on_lang_changed)
        lay.addWidget(lang_lab); lay.addWidget(self.cb_lang); lay.addSpacing(8)
        a = QLabel('PS5VietHoa\nPhước Lê & Mèo Mặt Căng')
        a.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        a.setStyleSheet(f'color:{DIM}; font-size:11px;')
        lay.addWidget(a)
        return f

    # ---------- TAB API ----------
    def _tab_api(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)

        # format
        fmt = QFrame(); fmt.setObjectName('card'); fl = QHBoxLayout(fmt); fl.setContentsMargins(14, 10, 14, 10)
        fl.addWidget(QLabel(self.t('api_format')))
        self.rb_openai = QRadioButton('OpenAI-compatible'); self.rb_anthropic = QRadioButton('Anthropic')
        self.rb_openai.setChecked(True)
        self.api_group = QButtonGroup(self); self.api_group.addButton(self.rb_openai); self.api_group.addButton(self.rb_anthropic)
        self.rb_openai.toggled.connect(self._on_provider_change)
        fl.addWidget(self.rb_openai); fl.addWidget(self.rb_anthropic); fl.addStretch(1)
        lay.addWidget(fmt)

        grid = QFrame(); grid.setObjectName('card'); g = QGridLayout(grid); g.setContentsMargins(14, 12, 14, 12); g.setSpacing(8)
        g.addWidget(QLabel(self.t('base_url')), 0, 0)
        self.ed_base = QLineEdit()
        self.ed_base.setToolTip(self.t('base_tip'))
        g.addWidget(self.ed_base, 0, 1, 1, 3)

        g.addWidget(QLabel(self.t('api_keys_label')), 1, 0)
        self.ed_keys = QPlainTextEdit(); self.ed_keys.setFixedHeight(72)
        self.ed_keys.setPlaceholderText(self.t('keys_ph'))
        g.addWidget(self.ed_keys, 1, 1, 1, 3)

        g.addWidget(QLabel(self.t('model_default_label')), 2, 0)
        self.cb_model = QComboBox(); self.cb_model.setEditable(True)
        self.cb_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)   # gõ tự do, không tự chèn rác
        self.cb_model.lineEdit().setPlaceholderText(self.t('model_ph'))
        self._init_model_completer(self.cb_model)
        g.addWidget(self.cb_model, 2, 1, 1, 2)
        self.btn_models = QPushButton(self.t('btn_fetch_models')); self.btn_models.clicked.connect(self._fetch_models)
        g.addWidget(self.btn_models, 2, 3)

        self.cb_auto_switch = QCheckBox(self.t('auto_switch'))
        self.cb_auto_switch.setToolTip(self.t('auto_switch_tip'))
        g.addWidget(self.cb_auto_switch, 3, 0, 1, 4)

        g.addWidget(QLabel('max_tokens:'), 4, 0)
        self.sp_maxtok = QSpinBox(); self.sp_maxtok.setRange(256, 1000000); self.sp_maxtok.setValue(8192); self.sp_maxtok.setSingleStep(512)
        g.addWidget(self.sp_maxtok, 4, 1)
        self.cb_send_temp = QCheckBox('temperature:'); self.cb_send_temp.setChecked(True)
        self.cb_send_temp.setToolTip(self.t('send_temp_tip'))
        self.cb_send_temp.toggled.connect(lambda on: self.sp_temp.setEnabled(on))
        g.addWidget(self.cb_send_temp, 4, 2)
        self.sp_temp = QDoubleSpinBox(); self.sp_temp.setRange(0.0, 2.0); self.sp_temp.setSingleStep(0.1); self.sp_temp.setValue(0.3)
        g.addWidget(self.sp_temp, 4, 3)

        g.addWidget(QLabel(self.t('timeout_label')), 5, 0)
        self.sp_timeout = QSpinBox(); self.sp_timeout.setRange(15, 600); self.sp_timeout.setValue(180)
        g.addWidget(self.sp_timeout, 5, 1)
        g.addWidget(QLabel(self.t('workers_label')), 5, 2)
        self.sp_workers = QSpinBox(); self.sp_workers.setRange(1, 10000); self.sp_workers.setValue(8)
        g.addWidget(self.sp_workers, 5, 3)

        g.addWidget(QLabel(self.t('lines_label')), 6, 0)
        self.sp_maxlines = QSpinBox(); self.sp_maxlines.setRange(5, 1000); self.sp_maxlines.setValue(50)
        g.addWidget(self.sp_maxlines, 6, 1)
        self.cb_context_1m = QCheckBox(self.t('context_1m')); self.cb_context_1m.setToolTip(self.t('context_1m_tip'))
        g.addWidget(self.cb_context_1m, 6, 2, 1, 2)
        lay.addWidget(grid)

        row = QHBoxLayout()
        self.btn_test = QPushButton(self.t('btn_test')); self.btn_test.clicked.connect(self._test_conn)
        self.btn_save = QPushButton(self.t('btn_save_cfg')); self.btn_save.clicked.connect(self._save_config_clicked)
        self.cb_debug = QCheckBox(self.t('debug_console')); self.cb_debug.setChecked(True)
        self.cb_debug.setToolTip(self.t('debug_tip'))
        self.lbl_api_status = QLabel(''); self.lbl_api_status.setObjectName('muted')
        row.addWidget(self.btn_test); row.addWidget(self.btn_save); row.addWidget(self.cb_debug)
        row.addWidget(self.lbl_api_status, 1); lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _on_provider_change(self):
        self.btn_models.setEnabled(self.rb_openai.isChecked())

    # ---------- MODEL SELECTION (mặc định ở tab API; tab Prompt/Dịch override) ----------
    def _init_model_completer(self, combo):
        """Completer gõ-gợi-ý theo chuỗi con (dùng chung cho mọi combobox model)."""
        _cmp = combo.completer()
        if _cmp:
            _cmp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            _cmp.setFilterMode(Qt.MatchFlag.MatchContains)
            _cmp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def _make_model_combo(self):
        """Combobox model phụ (tab Prompt/Dịch): editable, có mục '(Theo mặc định)' ở đầu."""
        c = QComboBox(); c.setEditable(True)
        c.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        c.addItem(self.t('model_default_item'))
        c.lineEdit().setPlaceholderText(self.t('model_default_item'))
        c.setToolTip(self.t('model_sel_tip'))
        self._init_model_completer(c)
        return c

    def _reset_combo(self, combo, items, keep):
        combo.blockSignals(True)
        combo.clear(); combo.addItems(items)
        if keep: combo.setCurrentText(keep)
        combo.blockSignals(False)

    def _fill_model_combos(self, models):
        """Đổ danh sách model (đã fetch) vào CẢ 3 combobox, GIỮ lựa chọn hiện tại.
        API = danh sách thuần; Prompt/Dịch = '(Theo mặc định)' + danh sách."""
        models = list(models or [])
        self._reset_combo(self.cb_model, models, self.cb_model.currentText().strip())
        default_item = self.t('model_default_item')
        for combo in (self.cb_model_prompt, self.cb_model_tr):
            self._reset_combo(combo, [default_item] + models, combo.currentText().strip() or default_item)

    def _set_model_combo(self, combo, value):
        """Đặt giá trị combo phụ: rỗng -> '(Theo mặc định)' (index 0); ngược lại -> model cụ thể."""
        if value: combo.setCurrentText(value)
        else: combo.setCurrentIndex(0)

    def _resolve_model(self, combo):
        """Đọc model từ combo phụ; '' nếu đang để '(Theo mặc định)' (sẽ dùng model mặc định)."""
        txt = combo.currentText().strip()
        return '' if (not txt or txt == self.t('model_default_item')) else txt

    # ---------- TAB SYSTEM PROMPT ----------
    def _tab_prompt(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)
        top = QFrame(); top.setObjectName('card'); g = QGridLayout(top); g.setContentsMargins(14, 12, 14, 12); g.setSpacing(8)
        g.addWidget(QLabel(self.t('game_name')), 0, 0)
        self.ed_game = QLineEdit(); self.ed_game.setPlaceholderText(self.t('game_ph'))
        g.addWidget(self.ed_game, 0, 1, 1, 3)
        g.addWidget(QLabel(self.t('eng_file')), 1, 0)
        self.ed_sample = QLineEdit(); g.addWidget(self.ed_sample, 1, 1, 1, 2)
        b = QPushButton(self.t('btn_browse')); b.clicked.connect(lambda: self._pick_into(self.ed_sample)); g.addWidget(b, 1, 3)
        self.lbl_sample = QLabel(''); self.lbl_sample.setObjectName('muted'); self.lbl_sample.setWordWrap(True)
        g.addWidget(self.lbl_sample, 2, 1, 1, 3)
        g.addWidget(QLabel(self.t('genre_tone')), 3, 0)
        self.cb_tone = QComboBox(); self.cb_tone.addItems(list(E.TONES.keys())); g.addWidget(self.cb_tone, 3, 1, 1, 2)
        g.addWidget(QLabel(self.t('extra_note')), 4, 0)
        self.ed_note = QLineEdit(); self.ed_note.setPlaceholderText(self.t('note_ph'))
        g.addWidget(self.ed_note, 4, 1, 1, 3)
        g.addWidget(QLabel(self.t('model_prompt_label')), 5, 0)
        self.cb_model_prompt = self._make_model_combo()
        g.addWidget(self.cb_model_prompt, 5, 1, 1, 3)
        lay.addWidget(top)
        self.ed_sample.textChanged.connect(self._update_sample_tokens)   # đổi file mẫu -> đếm token (nền)

        row = QHBoxLayout()
        self.btn_gen = QPushButton(self.t('btn_gen')); self.btn_gen.setObjectName('primary'); self.btn_gen.clicked.connect(self._gen_prompt)
        b_save = QPushButton(self.t('btn_save_prompt')); b_save.clicked.connect(self._save_prompt)
        b_load = QPushButton(self.t('btn_load_prompt')); b_load.clicked.connect(self._load_prompt)
        b_clear = QPushButton(self.t('btn_clear')); b_clear.clicked.connect(lambda: self.ed_prompt.setPlainText(''))
        row.addWidget(self.btn_gen); row.addWidget(b_save); row.addWidget(b_load); row.addWidget(b_clear); row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(QLabel(self.t('prompt_hint')))
        self.ed_prompt = QPlainTextEdit()
        sp = os.path.join(BASE, self.cfg.get('sysprompt_path', 'system_prompt.txt'))
        if os.path.exists(sp): self.ed_prompt.setPlainText(E.read_text(sp))
        lay.addWidget(self.ed_prompt, 1)
        return w

    # ---------- TAB DỊCH ----------
    def _tab_translate(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(8)
        files = QFrame(); files.setObjectName('card'); g = QGridLayout(files); g.setContentsMargins(14, 12, 14, 12); g.setSpacing(8)
        # chế độ: File đơn / Cả thư mục
        mrow = QHBoxLayout(); mrow.setSpacing(14)
        mrow.addWidget(QLabel(self.t('tr_mode')))
        self.rb_mode_file = QRadioButton(self.t('mode_file')); self.rb_mode_folder = QRadioButton(self.t('mode_folder'))
        self.rb_mode_file.setChecked(True)
        self.mode_group = QButtonGroup(self); self.mode_group.addButton(self.rb_mode_file); self.mode_group.addButton(self.rb_mode_folder)
        self.rb_mode_folder.toggled.connect(self._on_mode_change)
        mrow.addWidget(self.rb_mode_file); mrow.addWidget(self.rb_mode_folder); mrow.addStretch(1)
        g.addLayout(mrow, 0, 0, 1, 4)

        self.lbl_src_cap = QLabel(self.t('src_file')); g.addWidget(self.lbl_src_cap, 1, 0)
        self.ed_src = QLineEdit(); g.addWidget(self.ed_src, 1, 1, 1, 2)
        b1 = QPushButton(self.t('btn_browse')); b1.clicked.connect(self._pick_src); g.addWidget(b1, 1, 3)
        self.lbl_out_cap = QLabel(self.t('out_file')); g.addWidget(self.lbl_out_cap, 2, 0)
        self.ed_out = QLineEdit(); g.addWidget(self.ed_out, 2, 1, 1, 2)
        b2 = QPushButton(self.t('btn_browse')); b2.clicked.connect(self._pick_out); g.addWidget(b2, 2, 3)
        # đuôi file (chỉ hiện ở chế độ thư mục)
        self.lbl_ext_cap = QLabel(self.t('ext_label')); g.addWidget(self.lbl_ext_cap, 3, 0)
        self.ed_ext = QLineEdit(); self.ed_ext.setPlaceholderText(self.t('ext_ph')); self.ed_ext.setToolTip(self.t('ext_tip'))
        g.addWidget(self.ed_ext, 3, 1, 1, 3)
        self.lbl_ext_cap.setVisible(False); self.ed_ext.setVisible(False)
        self.lbl_resume = QLabel(''); self.lbl_resume.setObjectName('muted')
        g.addWidget(self.lbl_resume, 4, 1, 1, 3)
        lay.addWidget(files)
        # cập nhật mốc đã dịch khi đổi file/thư mục/đuôi (ghi nhớ tiến độ -> không dịch lại từ đầu)
        self.ed_src.textChanged.connect(self._update_resume)
        self.ed_out.textChanged.connect(self._update_resume)
        self.ed_ext.textChanged.connect(self._update_resume)

        mdl = QFrame(); mdl.setObjectName('card'); mh = QHBoxLayout(mdl); mh.setContentsMargins(14, 10, 14, 10); mh.setSpacing(10)
        mh.addWidget(QLabel(self.t('model_translate_label')))
        self.cb_model_tr = self._make_model_combo()
        mh.addWidget(self.cb_model_tr, 1)
        self.cb_byte_limit = QCheckBox(self.t('byte_limit')); self.cb_byte_limit.setToolTip(self.t('byte_limit_tip'))
        self.cb_byte_limit.toggled.connect(self._on_byte_limit_toggle)
        mh.addWidget(self.cb_byte_limit)
        lay.addWidget(mdl)

        ctl = QHBoxLayout()
        self.btn_start = QPushButton(self.t('btn_start')); self.btn_start.setObjectName('primary'); self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton(self.t('btn_stop')); self.btn_stop.setObjectName('danger'); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self._stop)
        self.lbl_use_prompt = QLabel(''); self.lbl_use_prompt.setObjectName('muted')
        ctl.addWidget(self.btn_start); ctl.addWidget(self.btn_stop); ctl.addWidget(self.lbl_use_prompt, 1)
        lay.addLayout(ctl)

        # thẻ thống kê
        cards = QHBoxLayout()
        self.card_total = StatCard(self.t('card_translated')); self.card_speed = StatCard(self.t('card_speed'))
        self.card_eta = StatCard(self.t('card_eta')); self.card_err = StatCard(self.t('card_err'))
        for c in (self.card_total, self.card_speed, self.card_eta, self.card_err): cards.addWidget(c)
        lay.addLayout(cards)

        # tiến độ cấp THƯ MỤC (chỉ hiện ở chế độ thư mục); thanh/lưới/thẻ bên dưới là tiến độ FILE hiện tại
        self.lbl_folder = QLabel(''); self.lbl_folder.setObjectName('muted'); self.lbl_folder.setVisible(False)
        lay.addWidget(self.lbl_folder)

        self.pbar = QProgressBar(); self.pbar.setRange(0, 100); self.pbar.setValue(0); lay.addWidget(self.pbar)

        # lưới lô + chú thích
        gridcard = QFrame(); gridcard.setObjectName('card'); gl = QVBoxLayout(gridcard); gl.setContentsMargins(12, 10, 12, 10)
        head = QHBoxLayout()
        _tt = QLabel(self.t('batch_progress')); _tt.setStyleSheet(f'color:{FG}; font-weight:700;')
        head.addWidget(_tt); head.addStretch(1)
        for _c, _n in ((STATE_COLOR[ST_QUEUED].name(), self.t('stt_queued')), (YEL, self.t('stt_running')),
                       (GREEN, self.t('stt_done')), (ORANGE, self.t('stt_retry')), (RED, self.t('stt_error'))):
            head.addWidget(self._dot_legend(_c, _n))
        gl.addLayout(head)
        self.grid = BatchGridWidget(); gl.addWidget(self.grid)
        self.grid.names = {ST_QUEUED: self.t('stt_queued'), ST_RUNNING: self.t('stt_running'),
                           ST_DONE: self.t('stt_done'), ST_ERROR: self.t('stt_error'), ST_RETRY: self.t('stt_retry')}
        self.grid.tip = {'batch': self.t('tip_batch'), 'model': 'model: %s',
                         'lines': self.t('tip_lines'), 'err': self.t('tip_err')}
        lay.addWidget(gridcard)

        # bảng worker + log cạnh nhau
        bottom = QHBoxLayout()
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels([self.t('tbl_thread'), self.t('tbl_batch'), self.t('tbl_model'), self.t('tbl_status')])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setMinimumWidth(380); self.tbl.setMaximumWidth(460)
        bottom.addWidget(self.tbl)
        self.log = QPlainTextEdit(); self.log.setObjectName('log'); self.log.setReadOnly(True)
        bottom.addWidget(self.log, 1)
        lay.addLayout(bottom, 1)
        return w

    # ---------- TAB XEM TRƯỚC (đối chiếu key / EN / VI) ----------
    def _tab_preview(self):
        self._preview_loading = False; self._preview_count = 0
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(8)
        bar = QHBoxLayout()
        self.btn_preview = QPushButton(self.t('btn_refresh')); self.btn_preview.clicked.connect(self._load_preview)
        self.ed_search = QLineEdit(); self.ed_search.setPlaceholderText(self.t('search_ph'))
        self.ed_search.textChanged.connect(self._filter_preview)
        self.cb_only_pending = QCheckBox(self.t('only_pending')); self.cb_only_pending.stateChanged.connect(self._filter_preview)
        self.cb_only_over = QCheckBox(self.t('only_over')); self.cb_only_over.stateChanged.connect(self._filter_preview)
        bar.addWidget(self.btn_preview); bar.addWidget(self.ed_search, 1)
        bar.addWidget(self.cb_only_pending); bar.addWidget(self.cb_only_over)
        lay.addLayout(bar)
        self.lbl_preview = QLabel(self.t('pv_not_loaded'))
        self.lbl_preview.setObjectName('muted'); lay.addWidget(self.lbl_preview)
        # QTableView + model ẢO HÓA -> mở tức thì kể cả file rất lớn (không đơ UI)
        self.preview_model = PreviewModel()
        self.preview_model.head = [self.t('col_key'), self.t('col_en'), self.t('col_vi'),
                                   self.t('col_byte_en'), self.t('col_byte_vi')]
        self.preview_proxy = PreviewFilter(); self.preview_proxy.setSourceModel(self.preview_model)
        self.preview = QTableView()
        self.preview.setModel(self.preview_proxy)
        self.preview.verticalHeader().setVisible(False)
        self.preview.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.preview.setWordWrap(False); self.preview.setAlternatingRowColors(False)
        self.preview.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        hh = self.preview.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.preview.setColumnWidth(0, 240)
        lay.addWidget(self.preview, 1)
        return w

    def _load_preview(self):
        if self._preview_loading: return
        src = self.ed_src.text().strip(); out = self.ed_out.text().strip()
        if not os.path.isfile(src):
            self.lbl_preview.setText(self.t('pv_no_src'))
            self.preview_model.set_rows([]); self._preview_count = 0; return
        # đọc + parse + đối chiếu Ở THREAD NỀN -> không đơ UI khi file lớn / đang dịch
        self._preview_loading = True; self.btn_preview.setEnabled(False)
        self.lbl_preview.setText(self.t('pv_loading'))
        bl = self.cb_byte_limit.isChecked() if hasattr(self, 'cb_byte_limit') else False
        t = FnThread(lambda: E.build_preview_rows(src, out, bl))
        t.done.connect(self._on_preview_loaded); self._threads.append(t); t.start()

    def _on_preview_loaded(self, res):
        self._preview_loading = False; self.btn_preview.setEnabled(True)
        if isinstance(res, Exception):
            self.lbl_preview.setText(self.t('pv_load_err', str(res)[:120])); return
        rows, st = res
        self._preview_count = len(rows)
        self.preview_model.set_rows(rows)          # set 1 phát, model ảo hóa -> tức thì
        self.lbl_preview.setText(self.t('pv_summary', len(rows), st['done'], st['pending'],
                                         st['bad'], st.get('over', 0)))
        self._filter_preview()

    def _filter_preview(self):
        only = self.cb_only_pending.isChecked(); q = self.ed_search.text().strip()
        over = self.cb_only_over.isChecked() if hasattr(self, 'cb_only_over') else False
        if only or over or q:
            self.preview_model.load_all()      # đang lọc -> cần thấy toàn bộ để kết quả đủ
        self.preview_proxy.set_only(only)
        self.preview_proxy.set_only_over(over)
        self.preview_proxy.set_query(q)
        if self._preview_count and (q or only or over):
            self.lbl_preview.setText(self.t('pv_filtered', self.preview_proxy.rowCount(), self._preview_count))

    def _on_byte_limit_toggle(self, _on):
        # đổi trạng thái ép byte -> nếu bảng Xem trước đã tải thì nạp lại để cập nhật tô màu / nghi lỗi
        if getattr(self, '_preview_count', 0):
            self._load_preview()

    def _on_tab_changed(self, idx):
        if idx == 3 and self._preview_count == 0:      # 3 = tab XEM TRƯỚC / PREVIEW
            self._load_preview()

    # ---------- HELPER TRỰC QUAN (legend + tab HƯỚNG DẪN) ----------
    def _dot_legend(self, color, text):
        """Một ô màu nhỏ + nhãn (chú thích trạng thái lô ở tab DỊCH)."""
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(8, 0, 0, 0); h.setSpacing(6)
        dot = QLabel(); dot.setFixedSize(12, 12)
        dot.setStyleSheet('background:%s; border-radius:3px;' % color)
        lab = QLabel(text); lab.setStyleSheet(f'color:{MUTED};')
        h.addWidget(dot); h.addWidget(lab)
        return w

    def _chip(self, text, bg, fg, mono=False):
        """Nhãn dạng 'viên thuốc' (token mã, ví dụ...). PlainText để hiện cả <thẻ>."""
        l = QLabel(text); l.setTextFormat(Qt.TextFormat.PlainText)
        fam = 'font-family:Menlo,Consolas,monospace;' if mono else ''
        l.setStyleSheet(f'background:{bg}; color:{fg}; border:1px solid {BORDER}; '
                        f'border-radius:6px; padding:2px 9px; font-weight:600; {fam}')
        return l

    def _guide_heading(self, text):
        l = QLabel(text)
        l.setStyleSheet(f'color:{ACC}; font-size:15px; font-weight:800; margin-top:8px;')
        return l

    def _guide_banner(self, title, html):
        f = QFrame(); f.setObjectName('card')
        v = QVBoxLayout(f); v.setContentsMargins(18, 16, 18, 16); v.setSpacing(6)
        t = QLabel(title); t.setStyleSheet(f'color:{FG}; font-size:20px; font-weight:800;')
        d = QLabel(html); d.setTextFormat(Qt.TextFormat.RichText); d.setWordWrap(True)
        d.setStyleSheet(f'color:{MUTED}; font-size:13px;')
        v.addWidget(t); v.addWidget(d)
        return f

    def _guide_step(self, num, title, lines):
        f = QFrame(); f.setObjectName('card')
        h = QHBoxLayout(f); h.setContentsMargins(14, 14, 16, 14); h.setSpacing(14)
        badge = QLabel(str(num)); badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f'background:{ACC}; color:{INK}; font-size:16px; '
                            f'font-weight:800; border-radius:10px;')
        h.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout(); box.setSpacing(6)
        t = QLabel(title); t.setStyleSheet(f'color:{FG}; font-size:14px; font-weight:700;')
        box.addWidget(t)
        body_html = '<br>'.join("<span style='color:%s'>&#9656;</span>&nbsp; %s" % (ACC, ln)
                                for ln in lines)
        body = QLabel(body_html); body.setTextFormat(Qt.TextFormat.RichText); body.setWordWrap(True)
        body.setStyleSheet(f'color:{MUTED}; font-size:13px;')
        box.addWidget(body)
        h.addLayout(box, 1)
        return f

    def _guide_invariants(self, rows, example_html):
        f = QFrame(); f.setObjectName('card')
        v = QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(11)
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(11)
        grid.setColumnStretch(1, 1)
        for r, (toks, desc) in enumerate(rows):
            chips = QWidget(); ch = QHBoxLayout(chips); ch.setContentsMargins(0, 0, 0, 0); ch.setSpacing(6)
            for tk in toks: ch.addWidget(self._chip(tk, ENTRY, ACC, mono=True))
            ch.addStretch(1)
            grid.addWidget(chips, r, 0)
            d = QLabel(desc); d.setWordWrap(True); d.setStyleSheet(f'color:{MUTED};')
            grid.addWidget(d, r, 1)
        v.addLayout(grid)
        sep = QFrame(); sep.setObjectName('sep'); v.addWidget(sep)
        ex = QLabel(example_html); ex.setTextFormat(Qt.TextFormat.RichText); ex.setWordWrap(True)
        ex.setStyleSheet(f'color:{FG};')
        v.addWidget(ex)
        return f

    def _guide_states(self, items):
        f = QFrame(); f.setObjectName('card')
        g = QGridLayout(f); g.setContentsMargins(16, 14, 16, 14)
        g.setHorizontalSpacing(14); g.setVerticalSpacing(11)
        g.setColumnStretch(1, 1); g.setColumnStretch(3, 1)
        for i, (c, name, desc) in enumerate(items):
            row, col = i // 2, (i % 2) * 2
            cell = QWidget(); hb = QHBoxLayout(cell); hb.setContentsMargins(0, 0, 0, 0); hb.setSpacing(8)
            dot = QLabel(); dot.setFixedSize(16, 16)
            dot.setStyleSheet('background:%s; border-radius:4px;' % c)
            nm = QLabel(name); nm.setStyleSheet(f'color:{FG}; font-weight:700;')
            hb.addWidget(dot); hb.addWidget(nm)
            g.addWidget(cell, row, col)
            d = QLabel(desc); d.setWordWrap(True); d.setStyleSheet(f'color:{MUTED};')
            g.addWidget(d, row, col + 1)
        return f

    def _guide_trouble(self, heads, rows):
        f = QFrame(); f.setObjectName('card')
        g = QGridLayout(f); g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(0); g.setVerticalSpacing(0)
        g.setColumnStretch(0, 3); g.setColumnStretch(1, 4); g.setColumnStretch(2, 5)

        def cell(text, r, c, head=False):
            l = QLabel(text); l.setWordWrap(True); l.setTextFormat(Qt.TextFormat.RichText)
            l.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            if head:
                l.setStyleSheet(f'background:{ENTRY}; color:{MUTED}; font-weight:700; padding:9px 13px;')
            else:
                bg = '#1b2536' if (r % 2) else CARD
                l.setStyleSheet(f'background:{bg}; color:{FG}; padding:9px 13px;')
            g.addWidget(l, r, c)

        for c, h in enumerate(heads): cell(h, 0, c, head=True)
        for r, row in enumerate(rows, 1):
            for c, txt in enumerate(row): cell(txt, r, c)
        return f

    def _guide_tips(self, tips):
        f = QFrame(); f.setObjectName('card')
        v = QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(9)
        for tip in tips:
            cont = QWidget(); row = QHBoxLayout(cont); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(10)
            b = QLabel('▸'); b.setStyleSheet(f'color:{ACC}; font-weight:800;')
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            l = QLabel(tip); l.setTextFormat(Qt.TextFormat.RichText); l.setWordWrap(True)
            l.setStyleSheet(f'color:{MUTED};')
            row.addWidget(l, 1)
            v.addWidget(cont)
        return f

    # ---------- TAB HƯỚNG DẪN / GUIDE ----------
    def _tab_guide(self):
        gd = _guide_data(self.lang)
        outer = QWidget(); ol = QVBoxLayout(outer); ol.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ol.addWidget(scroll)
        w = QWidget(); scroll.setWidget(w)
        lay = QVBoxLayout(w); lay.setContentsMargins(4, 4, 12, 14); lay.setSpacing(14)

        lay.addWidget(self._guide_banner(gd['banner_title'], gd['banner_html']))

        lay.addWidget(self._guide_heading(gd['h_process']))
        for i, (title, lines) in enumerate(gd['steps'], 1):
            lay.addWidget(self._guide_step(i, title, lines))

        lay.addWidget(self._guide_heading(gd['h_invariants']))
        lay.addWidget(self._guide_invariants(gd['inv_rows'], gd['inv_example']))

        lay.addWidget(self._guide_heading(gd['h_states']))
        states_items = [(STATE_GUIDE_COLORS[i], nm, desc) for i, (nm, desc) in enumerate(gd['states'])]
        lay.addWidget(self._guide_states(states_items))

        lay.addWidget(self._guide_heading(gd['h_trouble']))
        lay.addWidget(self._guide_trouble(gd['trouble_heads'], gd['trouble_rows']))

        lay.addWidget(self._guide_heading(gd['h_tips']))
        lay.addWidget(self._guide_tips(gd['tips']))

        lay.addStretch(1)
        return outer

    # ============================== CONFIG ==============================
    def _load_config(self):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f: return json.load(f)
        except Exception:
            return {'provider': 'openai', 'base_url': 'https://chat.trollllm.xyz/v1', 'keys': [],
                    'model': 'claude-sonnet-4-6', 'models': [], 'model_prompt': '', 'model_translate': '',
                    'max_tokens': 8192, 'temperature': 0.3, 'context_1m': False, 'debug': True,
                    'timeout': 180, 'workers': 8, 'maxlines': 50, 'maxchars': 8000, 'retries': 5,
                    'rounds': 6, 'mode': 'file', 'exts': '', 'byte_limit': False,
                    'sysprompt_path': 'system_prompt.txt', 'lang': 'vi'}

    # ---------- snapshot / restore (giữ ô nhập khi đổi ngôn ngữ -> rebuild) ----------
    def _snapshot_ui(self):
        return {
            'cfg': self._gather_cfg(),
            'model_items': [self.cb_model.itemText(i) for i in range(self.cb_model.count())],
            'game': self.ed_game.text(), 'sample': self.ed_sample.text(),
            'tone_idx': self.cb_tone.currentIndex(), 'note': self.ed_note.text(),
            'tab': self.tabs.currentIndex(), 'log': self.log.toPlainText(),
        }

    def _restore_ui(self, s):
        c = s['cfg']
        (self.rb_anthropic if c['provider'] == 'anthropic' else self.rb_openai).setChecked(True)
        self.ed_base.setText(c['base_url'])
        self.ed_keys.setPlainText('\n'.join(c['keys']))
        self._fill_model_combos(s['model_items'])
        self.cb_model.setCurrentText(c['model'])
        self._set_model_combo(self.cb_model_prompt, c.get('model_prompt', ''))
        self._set_model_combo(self.cb_model_tr, c.get('model_translate', ''))
        self.sp_maxtok.setValue(int(c['max_tokens'])); self.sp_temp.setValue(float(c['temperature']))
        self.cb_send_temp.setChecked(bool(c.get('send_temperature', True))); self.sp_temp.setEnabled(self.cb_send_temp.isChecked())
        self.cb_context_1m.setChecked(bool(c.get('context_1m', False)))
        self.cb_debug.setChecked(bool(c.get('debug', True)))
        self.sp_timeout.setValue(int(c['timeout'])); self.sp_workers.setValue(int(c['workers']))
        self.sp_maxlines.setValue(int(c['maxlines'])); self.cb_auto_switch.setChecked(bool(c['auto_switch']))
        self.ed_src.setText(c['src']); self.ed_out.setText(c['out'])
        self.ed_ext.setText(c.get('exts', '') or '')
        self.cb_byte_limit.setChecked(bool(c.get('byte_limit', False)))
        (self.rb_mode_folder if c.get('mode') == 'folder' else self.rb_mode_file).setChecked(True)
        self.ed_game.setText(s['game']); self.ed_sample.setText(s['sample'])
        self.cb_tone.setCurrentIndex(s['tone_idx']); self.ed_note.setText(s['note'])
        self.ed_prompt.setPlainText(c.get('sysprompt', ''))
        self.log.setPlainText(s['log'])
        self._on_provider_change(); self._on_mode_change()
        self.tabs.setCurrentIndex(s['tab'])

    def _persist_lang(self):
        """Ghi ngôn ngữ (+ cấu hình hiện tại) vào config.json."""
        try:
            c = self._gather_cfg(); c.pop('sysprompt', None)
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            self.cfg = c
        except Exception:
            pass

    def _apply_config_to_ui(self):
        c = self.cfg
        (self.rb_anthropic if c.get('provider') == 'anthropic' else self.rb_openai).setChecked(True)
        self.ed_base.setText(c.get('base_url', ''))
        self.ed_keys.setPlainText('\n'.join(c.get('keys', []) if isinstance(c.get('keys'), list) else []))
        models = c.get('models') or []
        self._fill_model_combos(models)
        self.cb_model.setCurrentText(c.get('model', '') or (models[0] if models else ''))
        self._set_model_combo(self.cb_model_prompt, c.get('model_prompt', ''))
        self._set_model_combo(self.cb_model_tr, c.get('model_translate', ''))
        self.sp_maxtok.setValue(int(c.get('max_tokens', 8192)))
        self.sp_temp.setValue(float(c.get('temperature', 0.3)))
        self.cb_send_temp.setChecked(bool(c.get('send_temperature', True))); self.sp_temp.setEnabled(self.cb_send_temp.isChecked())
        self.cb_context_1m.setChecked(bool(c.get('context_1m', False)))
        self.cb_debug.setChecked(bool(c.get('debug', True)))
        self.sp_timeout.setValue(int(c.get('timeout', 180)))
        self.sp_workers.setValue(int(c.get('workers', 8)))
        self.sp_maxlines.setValue(int(c.get('maxlines', 50)))
        self.cb_auto_switch.setChecked(bool(c.get('auto_switch', False)))
        self.ed_src.setText(c.get('src', '')); self.ed_out.setText(c.get('out', ''))
        self.ed_ext.setText(c.get('exts', '') or '')
        self.cb_byte_limit.setChecked(bool(c.get('byte_limit', False)))
        (self.rb_mode_folder if c.get('mode') == 'folder' else self.rb_mode_file).setChecked(True)
        self._on_provider_change()
        self._on_mode_change()      # đặt nhãn + ẩn/hiện ô đuôi + gọi _update_resume (mốc đã dịch đã lưu)

    def _gather_cfg(self):
        keys = [ln.strip() for ln in self.ed_keys.toPlainText().split('\n')
                if ln.strip() and not ln.strip().startswith('#')]
        model = self.cb_model.currentText().strip()        # model MẶC ĐỊNH (tab API)
        all_models = [self.cb_model.itemText(i) for i in range(self.cb_model.count())]
        # tab Prompt/Dịch có thể override; '' = '(Theo mặc định)' -> bám model mặc định
        model_prompt = self._resolve_model(self.cb_model_prompt) if hasattr(self, 'cb_model_prompt') else ''
        model_translate = self._resolve_model(self.cb_model_tr) if hasattr(self, 'cb_model_tr') else ''
        eff_tr = model_translate or model                  # model THỰC dùng khi dịch
        # CHỈ dùng model đang dùng; chỉ khi bật "tự đổi model" mới thêm các model dự phòng
        if self.cb_auto_switch.isChecked():
            models = list(dict.fromkeys([eff_tr] + all_models)) if eff_tr else all_models
        else:
            models = [eff_tr] if eff_tr else all_models[:1]
        return {
            'provider': 'anthropic' if self.rb_anthropic.isChecked() else 'openai',
            'base_url': self.ed_base.text().strip(),
            'keys': keys, 'model': model, 'models': models,
            'model_prompt': model_prompt, 'model_translate': model_translate,
            'auto_switch': self.cb_auto_switch.isChecked(),
            'max_tokens': self.sp_maxtok.value(), 'temperature': self.sp_temp.value(),
            'send_temperature': self.cb_send_temp.isChecked(),
            'context_1m': self.cb_context_1m.isChecked() if hasattr(self, 'cb_context_1m') else False,
            'debug': self.cb_debug.isChecked() if hasattr(self, 'cb_debug') else True,
            'timeout': self.sp_timeout.value(), 'workers': self.sp_workers.value(),
            'maxlines': self.sp_maxlines.value(), 'maxchars': int(self.cfg.get('maxchars', 8000)),
            'retries': int(self.cfg.get('retries', 5)), 'rounds': int(self.cfg.get('rounds', 6)),
            'src': self.ed_src.text().strip(), 'out': self.ed_out.text().strip(),
            'mode': 'folder' if self._folder_mode() else 'file',
            'exts': self.ed_ext.text().strip() if hasattr(self, 'ed_ext') else '',
            'byte_limit': self.cb_byte_limit.isChecked() if hasattr(self, 'cb_byte_limit') else False,
            'sysprompt': self.ed_prompt.toPlainText().strip(),
            'sysprompt_path': self.cfg.get('sysprompt_path', 'system_prompt.txt'),
            'lang': self.lang,
        }

    def _save_config_clicked(self):
        c = self._gather_cfg(); c.pop('sysprompt', None)
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            self.cfg = c
            self.lbl_api_status.setText(self.t('st_saved_cfg')); self.lbl_api_status.setStyleSheet(f'color:{GREEN};')
        except Exception as e:
            QMessageBox.critical(self, self.t('dlg_err'), self.t('dlg_cant_save_cfg', e))

    # ============================== API ACTIONS ==============================
    def _provider_from_ui(self):
        c = self._gather_cfg()
        return E.make_provider(c), (c['keys'][0] if c['keys'] else None), c['model']

    def _fetch_models(self):
        prov, key, _ = self._provider_from_ui()
        if not key:
            QMessageBox.warning(self, self.t('dlg_missing_key_t'), self.t('dlg_missing_key_m')); return
        self.btn_models.setEnabled(False); self.lbl_api_status.setText(self.t('st_fetching_models'))
        self.lbl_api_status.setStyleSheet(f'color:{MUTED};')
        t = FnThread(lambda: E.list_models(prov, key))
        t.done.connect(lambda r: self._on_models(r)); self._threads.append(t); t.start()

    def _on_models(self, r):
        self.btn_models.setEnabled(self.rb_openai.isChecked())
        if isinstance(r, Exception) or not r:
            self.lbl_api_status.setText(self.t('st_models_fail'))
            self.lbl_api_status.setStyleSheet(f'color:{ORANGE};'); return
        self._fill_model_combos(r)      # đổ vào CẢ 3 combobox (API + Prompt + Dịch), giữ lựa chọn
        self.lbl_api_status.setText(self.t('st_models_ok', len(r))); self.lbl_api_status.setStyleSheet(f'color:{GREEN};')

    def _test_conn(self):
        prov, key, model = self._provider_from_ui()
        if not key:
            QMessageBox.warning(self, self.t('dlg_missing_key_t'), self.t('dlg_missing_key_m')); return
        if not model:
            QMessageBox.warning(self, self.t('dlg_missing_model_t'), self.t('dlg_missing_model_m')); return
        self.btn_test.setEnabled(False); self.lbl_api_status.setText(self.t('st_testing'))
        self.lbl_api_status.setStyleSheet(f'color:{MUTED};')
        t = FnThread(lambda: E.test_connection(prov, key, model))
        t.done.connect(lambda r: self._on_test(r)); self._threads.append(t); t.start()

    def _on_test(self, r):
        self.btn_test.setEnabled(True)
        if isinstance(r, Exception):
            self.lbl_api_status.setText(self.t('st_err', str(r)[:100])); self.lbl_api_status.setStyleSheet(f'color:{RED};'); return
        ok, msg = r
        self.lbl_api_status.setText((self.t('st_conn_ok') if ok else self.t('st_conn_no')) + msg)
        self.lbl_api_status.setStyleSheet(f'color:{GREEN if ok else RED};')

    # ============================== SYSTEM PROMPT ACTIONS ==============================
    def _gen_prompt(self):
        prov, key, default_model = self._provider_from_ui()
        model = self._resolve_model(self.cb_model_prompt) or default_model   # model tab Prompt (hoặc mặc định)
        if not key:
            QMessageBox.warning(self, self.t('dlg_missing_key_t'), self.t('dlg_need_key_prompt')); return
        sample_file = self.ed_sample.text().strip()
        if not os.path.isfile(sample_file):
            QMessageBox.warning(self, self.t('dlg_missing_file_t'), self.t('dlg_missing_file_m')); return
        pairs = E.parse_doc(E.read_text(sample_file)).pairs
        sample = E.sample_for_prompt(pairs)
        if not sample:
            QMessageBox.warning(self, self.t('dlg_empty_file_t'), self.t('dlg_empty_file_m')); return
        game = self.ed_game.text().strip(); tone = E.TONES.get(self.cb_tone.currentText(), ''); note = self.ed_note.text().strip()
        self.btn_gen.setEnabled(False); self.btn_gen.setText(self.t('btn_gen_running'))
        self._append_log(self.t('log_gen_prompt', model, game or self.t('game_unnamed')))
        self._gen_prov = prov            # giữ tham chiếu để đọc last_truncated (prompt có bị cắt?) sau khi xong
        t = FnThread(lambda: E.gen_system_prompt(prov, key, model, sample, game, tone, note))
        t.done.connect(lambda r: self._on_gen(r)); self._threads.append(t); t.start()

    def _on_gen(self, r):
        self.btn_gen.setEnabled(True); self.btn_gen.setText(self.t('btn_gen'))
        if isinstance(r, Exception):
            msg = self.t('gen_too_many_tokens') if E.is_token_limit_error(str(r)) else str(r)[:300]
            QMessageBox.critical(self, self.t('dlg_gen_fail_t'), msg)
            self._append_log(self.t('log_gen_fail', msg[:150])); return
        self.ed_prompt.setPlainText(r)
        if getattr(getattr(self, '_gen_prov', None), 'last_truncated', False):   # prompt bị cắt do chạm trần output
            self._append_log(self.t('gen_truncated_warn'))
            QMessageBox.warning(self, self.t('dlg_gen_fail_t'), self.t('gen_truncated_warn'))
        else:
            self._append_log(self.t('log_gen_ok'))

    def _save_prompt(self):
        sp = os.path.join(BASE, self.cfg.get('sysprompt_path', 'system_prompt.txt'))
        try:
            with open(sp, 'w', encoding='utf-8', newline='\n') as f:
                f.write(self.ed_prompt.toPlainText().strip() + '\n')
            QMessageBox.information(self, self.t('dlg_saved_t'), self.t('dlg_prompt_saved_m', sp))
        except Exception as e:
            QMessageBox.critical(self, self.t('dlg_err'), str(e))

    def _load_prompt(self):
        p, _ = QFileDialog.getOpenFileName(self, self.t('fd_load_prompt'), BASE)
        if p: self.ed_prompt.setPlainText(E.read_text(p))

    def _fmt_int(self, n):
        """Số nguyên có dấu phân nhóm nghìn (vi: '.', en: ',')."""
        s = '{:,}'.format(int(n))
        return s.replace(',', '.') if self.lang == 'vi' else s

    def _update_sample_tokens(self):
        """Hiện tổng token (ước lượng) của file text tiếng Anh đã chọn — ĐỌC Ở THREAD NỀN."""
        p = self.ed_sample.text().strip()
        if not os.path.isfile(p):
            self.lbl_sample.setText(''); return
        self._sample_path = p
        t = FnThread(lambda: (p, E.sample_stats(E.read_text(p))))
        t.done.connect(self._on_sample_tokens); self._threads.append(t); t.start()

    def _on_sample_tokens(self, res):
        if isinstance(res, Exception): return
        p, st = res
        if p != getattr(self, '_sample_path', None): return   # kết quả của file cũ (đã đổi) -> bỏ
        self.lbl_sample.setText(self.t('sample_tok_info', self._fmt_int(st['tokens']),
                                       self._fmt_int(st['lines']), self._fmt_int(st['chars']),
                                       self._fmt_int(st['sample_tokens'])))

    # ============================== FILE PICKERS ==============================
    def _pick_into(self, edit, save=False):
        p = (QFileDialog.getSaveFileName(self, self.t('fd_save'), edit.text() or BASE)[0] if save
             else QFileDialog.getOpenFileName(self, self.t('fd_pick'), os.path.dirname(edit.text()) or BASE)[0])
        if p: edit.setText(p)

    def _folder_mode(self):
        return getattr(self, 'rb_mode_folder', None) is not None and self.rb_mode_folder.isChecked()

    def _on_mode_change(self):
        """Đổi chế độ File đơn <-> Cả thư mục: đổi nhãn + hiện/ẩn ô đuôi file."""
        folder = self._folder_mode()
        self.lbl_src_cap.setText(self.t('src_folder') if folder else self.t('src_file'))
        self.lbl_out_cap.setText(self.t('out_folder') if folder else self.t('out_file'))
        self.lbl_ext_cap.setVisible(folder); self.ed_ext.setVisible(folder)
        self.lbl_folder.setVisible(folder)
        self._update_resume()

    def _pick_src(self):
        if self._folder_mode():
            p = QFileDialog.getExistingDirectory(self, self.t('fd_pick_folder'), self.ed_src.text() or BASE)
            if not p: return
            self.ed_src.setText(p)
            if not self.ed_out.text().strip():
                self.ed_out.setText(E.default_out_folder(p))
            return
        p = QFileDialog.getOpenFileName(self, self.t('fd_pick_eng'), os.path.dirname(self.ed_src.text()) or BASE)[0]
        if not p: return
        self.ed_src.setText(p)
        if not self.ed_out.text().strip():
            d, f = os.path.split(p); n, ext = os.path.splitext(f)
            self.ed_out.setText(os.path.join(d, n + '_VI' + ext))

    def _pick_out(self):
        if self._folder_mode():
            start = self.ed_out.text() or self.ed_src.text() or BASE
            p = QFileDialog.getExistingDirectory(self, self.t('fd_pick_folder'), start)
            if p: self.ed_out.setText(p)
        else:
            self._pick_into(self.ed_out, save=True)

    # ============================== TRANSLATE CONTROL ==============================
    def _start(self):
        cfg = self._gather_cfg()
        folder = cfg.get('mode') == 'folder'
        if folder and not os.path.isdir(cfg['src']):
            QMessageBox.warning(self, self.t('dlg_err'), self.t('dlg_no_src_folder')); return
        if not folder and not os.path.isfile(cfg['src']):
            QMessageBox.warning(self, self.t('dlg_err'), self.t('dlg_no_src')); return
        if not cfg['out']:
            QMessageBox.warning(self, self.t('dlg_err'), self.t('dlg_no_out_folder') if folder else self.t('dlg_no_out')); return
        if not cfg['keys']:
            QMessageBox.warning(self, self.t('dlg_err'), self.t('dlg_no_key')); return
        if not cfg['models']:
            QMessageBox.warning(self, self.t('dlg_err'), self.t('dlg_no_model')); return
        self._persist_paths(cfg['src'], cfg['out'])   # nhớ đường dẫn để mở lại tự điền
        self.lbl_folder.setVisible(folder)
        if folder: self.lbl_folder.setText(self.t('folder_starting'))
        sp_desc = self.t('sp_custom', len(cfg['sysprompt'])) if cfg['sysprompt'] else self.t('sp_default')
        self.lbl_use_prompt.setText(self.t('use_prompt', sp_desc))
        # reset UI trực quan
        self.grid.reset(0); self.tbl.setRowCount(cfg['workers'])
        for i in range(cfg['workers']):
            self.tbl.setItem(i, 0, QTableWidgetItem('#%d' % (i + 1)))
            for j in (1, 2, 3): self.tbl.setItem(i, j, QTableWidgetItem('—'))
        self.card_total.set('—'); self.card_speed.set('—'); self.card_eta.set('—'); self.card_err.set('0')
        self.pbar.setValue(0)
        self.stop_event = threading.Event()
        self.orch = OrchestratorThread(cfg, self.bridge, self.stop_event)
        self.orch.finished.connect(self._on_thread_finished)
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        self.cb_lang.setEnabled(False)        # khóa đổi ngôn ngữ khi đang dịch (tránh rebuild)
        self.orch.start()

    def _stop(self):
        if self.stop_event: self.stop_event.set()
        self.btn_stop.setEnabled(False); self._append_log(self.t('log_stopping'))

    def _on_thread_finished(self):
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self.cb_lang.setEnabled(True)

    def _update_resume(self):
        """Hiển thị mốc đã dịch đã lưu (resume) theo file/thư mục hiện chọn."""
        src = self.ed_src.text().strip(); out = self.ed_out.text().strip()
        if self._folder_mode():           # chế độ thư mục: đếm nhanh số file khớp (KHÔNG đọc nội dung)
            if not os.path.isdir(src):
                self.lbl_resume.setText(''); return
            ov = E.folder_overview(src, out, self.ed_ext.text().strip())
            self.lbl_resume.setText(self.t('folder_none') if ov['files'] == 0
                                    else self.t('folder_overview', ov['files'], ov['have_out']))
            return
        if not os.path.isfile(src):       # isfile (không phải exists): path thư mục -> không gọi resume
            self.lbl_resume.setText(''); return
        st = E.resume_status(src, out)
        if st['total'] == 0:
            self.lbl_resume.setText('')
        elif st['done'] == 0:
            self.lbl_resume.setText(self.t('resume_none', st['total']))
        elif st['done'] >= st['total']:
            self.lbl_resume.setText(self.t('resume_done', st['total']))
        else:
            self.lbl_resume.setText(self.t('resume_partial', st['done'], st['total'], st['todo']))

    def _persist_paths(self, src, out):
        """Lưu src/out (+ cấu hình hiện tại) vào config.json để mở lại app tự điền -> resume dễ."""
        try:
            c = self._gather_cfg(); c.pop('sysprompt', None); c['src'] = src; c['out'] = out
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            self.cfg = c
        except Exception:
            pass

    # ============================== BRIDGE WIRING (slots chạy ở UI thread) ==============================
    def _wire_bridge(self):
        self.bridge.sig_progress.connect(self._on_progress)
        self.bridge.sig_batch_init.connect(self._on_batch_init)
        self.bridge.sig_batch.connect(self._on_batch)
        self.bridge.sig_worker.connect(self._on_worker)
        self.bridge.sig_log.connect(self._append_log)
        self.bridge.sig_stats.connect(self._on_stats)
        self.bridge.sig_finished.connect(self._on_finished)
        self.bridge.sig_folder_init.connect(self._on_folder_init)
        self.bridge.sig_folder_file.connect(self._on_folder_file)

    def _on_progress(self, e):
        self.pbar.setValue(e.get('pct', 0))
        self.card_total.set('%d/%d' % (e.get('done', 0), e.get('total', 0)), '%d%%' % e.get('pct', 0))
        rate = e.get('rate', 0) * 60
        self.card_speed.set('%.0f' % rate, self.t('sub_lines_min'))
        eta = e.get('eta_sec', 0)
        self.card_eta.set('%d:%02d' % (eta // 60, eta % 60), self.t('sub_left'))

    def _on_batch_init(self, e):
        self.grid.reset(e.get('n_batches', 0))
        self._append_log(self.t('log_batch_init', e.get('label', ''), e.get('n_batches', 0)))

    def _on_batch(self, e):
        self.grid.set_state(e.get('batch_id', -1), STATE_NUM.get(e.get('state'), ST_QUEUED),
                            {'model': e.get('model', ''), 'n_lines': e.get('n_lines'), 'err': e.get('err')})

    def _on_worker(self, e):
        slot = e.get('slot', -1)
        if 0 <= slot < self.tbl.rowCount():
            st = e.get('status', '')
            lab = {'translating': self.t('wk_translating'), 'waiting': self.t('wk_waiting'),
                   'idle': self.t('wk_idle')}.get(st, st)
            bid = e.get('batch_id')
            self.tbl.setItem(slot, 1, QTableWidgetItem(self.t('tbl_batch') + ' %d' % (bid + 1) if bid is not None else '—'))
            self.tbl.setItem(slot, 2, QTableWidgetItem(e.get('model', '') or '—'))
            self.tbl.setItem(slot, 3, QTableWidgetItem(lab))

    def _on_stats(self, e):
        self.card_err.set('%d' % e.get('err', 0), self.t('sub_retry', e.get('retries', 0)))

    def _on_folder_init(self, e):
        exts = e.get('exts') or []
        txt = self.t('folder_init', e.get('n_files', 0), ' '.join(exts) if exts else self.t('ext_all'))
        self.lbl_folder.setVisible(True); self.lbl_folder.setText(txt)

    def _on_folder_file(self, e):
        if e.get('state') == 'start':     # bắt đầu file mới -> cập nhật dòng tiến độ thư mục
            self.lbl_folder.setText(self.t('folder_progress', e.get('index', 0) + 1,
                                           e.get('total', 0), e.get('name', '')))

    def _on_finished(self, e):
        status = e.get('status'); msg = e.get('msg', '')
        self._append_log('=== %s ===' % msg)
        if self._folder_mode(): self.lbl_folder.setText(msg)
        self._load_preview()          # cập nhật bảng XEM TRƯỚC theo kết quả mới nhất
        self._update_resume()         # cập nhật mốc đã dịch
        if status == 'ok':
            self.pbar.setValue(100)
            QMessageBox.information(self, self.t('dlg_done_t'), msg)
        elif status == 'error':
            QMessageBox.critical(self, self.t('dlg_err'), msg)
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)

    # ============================== LOG (coalesced) ==============================
    def _append_log(self, s):
        self._log_buf.append('[%s] %s' % (time.strftime('%H:%M:%S'), s))

    def _flush_log(self):
        if not self._log_buf: return
        self.log.appendPlainText('\n'.join(self._log_buf)); self._log_buf.clear()
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ---------- misc ----------
    def closeEvent(self, e):
        if self.stop_event: self.stop_event.set()
        if self.orch and self.orch.isRunning(): self.orch.wait(2000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow(); win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
