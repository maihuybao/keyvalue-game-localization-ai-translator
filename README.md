# KeyValue Game Localization AI Translator

> Công cụ **dịch file localization game EN → VI** bằng AI, có giao diện đồ họa (PyQt6), dịch đa luồng, tự kiểm – tự sửa và resume khi gián đoạn.

Tác giả: **PS5VietHoa** — *Phước Lê & Mèo Mặt Căng*.

---

## Mục lục

- [Tính năng nổi bật](#tính-năng-nổi-bật)
- [Định dạng file hỗ trợ](#định-dạng-file-hỗ-trợ)
- [Cài đặt](#cài-đặt)
- [Cấu hình API](#cấu-hình-api)
- [Chạy ứng dụng](#chạy-ứng-dụng)
- [Hướng dẫn sử dụng (5 tab)](#hướng-dẫn-sử-dụng-5-tab)
- [Quy trình dịch điển hình](#quy-trình-dịch-điển-hình)
- [Bất biến giữ nguyên khi dịch](#bất-biến-giữ-nguyên-khi-dịch)
- [Resume — dịch tiếp khi gián đoạn](#resume--dịch-tiếp-khi-gián-đoạn)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Kiểm thử](#kiểm-thử)

---

## Tính năng nổi bật

- **Giao diện đồ họa PyQt6** — 5 tab trực quan, theme tối Slate, **song ngữ Việt / English** (đổi ngay ở header).
- **Dịch đa luồng** — chia file thành nhiều lô, chạy song song (`ThreadPoolExecutor`), trực quan hóa tiến độ realtime từng lô.
- **Tự sinh System Prompt** — phân tích tên game + mẫu text để viết prompt dịch nhất quán (glossary, xưng hô, tone).
- **Tự kiểm – tự sửa** — sau khi dịch, kiểm placeholder/thẻ; dòng lỗi được dịch lại nhiều vòng đến khi sạch.
- **Resume** — ghi nhớ mốc đã dịch; tắt giữa chừng mở lại vẫn dịch tiếp phần còn lại, không làm lại từ đầu.
- **2 chuẩn API**: OpenAI-compatible (`/v1/chat/completions`) và Anthropic (`/v1/messages`).
- **Đa định dạng input** — tự nhận diện `KEY=VALUE` hoặc format **Resident** (FF7 Rebirth). Xem mục dưới.

---

## Định dạng file hỗ trợ

Tool **tự nhận diện** định dạng khi mở file, không cần khai báo.

### 1) `KEY=VALUE` (mặc định)

Mỗi dòng một cặp; chỉ dịch phần **sau** dấu `=`. Dòng `#` là comment, dòng rỗng và dòng `KEY=KEY` được giữ nguyên.

```
# comment giữ nguyên
MENU_START=Start Game
HINT=Press {0} to continue
```

### 2) `Resident` — FF7 Rebirth (`Resident_TxtRes`)

Dòng đầu là **header ngôn ngữ** (vd `US`); sau đó là từng **block**: một dòng `$KEY` rồi **0..n dòng nội dung**. Mỗi dòng nội dung là **một biến thể độc lập** (tên hiển thị / mạo từ / số ít / số nhiều) và được **dịch riêng**.

```
US
$Item_E_ACC_0001
Power Wristguards
a pair of
pairs of
power wristguards
power wristguards
$UI_OK
OK
```

> File output giữ **nguyên cấu trúc, header và thứ tự** — chỉ thay nội dung đã dịch. Sau khi dịch xong, đổi tên file output về đúng đuôi gốc (vd `*.uasset.txt`) để import lại game.

---

## Cài đặt

Yêu cầu: **Python 3.9+**.

```bash
# 1. (Khuyến nghị) tạo môi trường ảo
python3 -m venv .venv && source .venv/bin/activate   # macOS/Linux

# 2. Cài dependency
pip install -r requirements.txt
```

`requirements.txt` gồm `httpx` (mạng, dùng cho engine) và `PyQt6` (giao diện).

---

## Cấu hình API

File `config.json` chứa **API key thật** nên **không được commit** (đã có trong `.gitignore`). Hãy tạo từ file mẫu:

```bash
cp config.example.json config.json
```

Rồi mở `config.json` và điền key của bạn vào mảng `keys`. Các trường chính:

| Trường | Ý nghĩa |
|---|---|
| `provider` | `openai` (OpenAI-compatible) hoặc `anthropic` |
| `base_url` | Domain API (vd `https://chat.trollllm.xyz`) — chỉ cần domain, tool tự thêm `/v1/...` |
| `keys` | Danh sách API key (xoay vòng khi nhiều key) |
| `model` / `models` | Model dùng để dịch / danh sách model dự phòng |
| `auto_switch` | `true` để tự đổi model khi gặp rate-limit/lỗi |
| `workers` | Số luồng dịch song song |
| `maxlines` / `maxchars` | Giới hạn mỗi lô (số dòng / số ký tự) |

> Bạn cũng có thể nhập toàn bộ thông số này trực tiếp trong tab **API** của ứng dụng, không cần sửa tay file JSON.

---

## Chạy ứng dụng

```bash
python3 app.py
```

Trên macOS có thể double-click **`run_tool.command`**.

---

## Hướng dẫn sử dụng (5 tab)

| Tab | Chức năng |
|---|---|
| **API** | Nhập `base_url`, API key, chọn model; **Kiểm tra kết nối** và **Lưu cấu hình**. |
| **System Prompt** | Nhập tên game/tone/ghi chú và **Tự sinh** prompt từ mẫu text, hoặc tự viết/chỉnh tay. |
| **Dịch** | Chọn file nguồn + file đích, bấm **Bắt đầu**; xem tiến độ realtime (lưới lô, worker, log). |
| **Xem trước** | Bảng đối chiếu **Key / EN / VI** (ảo hóa, mượt cả file vài chục nghìn dòng); lọc/tìm nhanh. |
| **Hướng dẫn** | Hướng dẫn trực quan ngay trong app (song ngữ). |

> Bộ chuyển **ngôn ngữ Việt / English** nằm ở góc phải header, đổi tức thì toàn bộ giao diện.

---

## Quy trình dịch điển hình

1. **Tab API** → điền `base_url` + key → **Kiểm tra kết nối** → **Lưu cấu hình**.
2. **Tab System Prompt** → điền tên game + tone → **Tự sinh** (hoặc dán prompt có sẵn) → **Lưu**.
3. **Tab Dịch** → chọn **file nguồn** (EN) và **file đích** (VI) → **Bắt đầu**.
4. Theo dõi tiến độ; khi xong, sang **Tab Xem trước** để đối chiếu và rà soát.
5. (Resident) Đổi tên file đích về đuôi gốc để import lại game.

---

## Bất biến giữ nguyên khi dịch

Engine kiểm tra để các token sau **không bị đổi/mất** trong bản dịch (số lượng và vị trí phải khớp bản gốc):

- Biến `{...}`, `{0}` ...
- Thẻ `<...>` — gồm cả `<cf>`, `<color=...>`, `<button=...>`, `<count=N>`, `<i>`, tag rỗng `<>` ... (format Resident)
- `[REDACTED]` và mã chữ-hoa trong ngoặc vuông
- Ký tự điều khiển `\n`, `\r`

Dòng vi phạm sẽ được **dịch lại tự động** qua các vòng tự-kiểm-tự-sửa (số vòng tối đa = `rounds`).

---

## Resume — dịch tiếp khi gián đoạn

- Mỗi lô xong, output được ghi **atomic** (`.tmp` → thay thế) và mốc đã dịch được append vào `<output>.done.txt`.
- **File output là nguồn chân lý**: chỉ coi một dòng là "đã xong" khi output thật sự có dòng đó. Xóa output (dù còn `.done.txt`) thì tool vẫn dịch lại đúng, không bỏ sót.
- Mở lại tool và bấm **Bắt đầu** trên cùng cặp file → chỉ dịch phần còn thiếu.

---

## Cấu trúc dự án

```
.
├── app.py                  # GUI PyQt6 (nơi DUY NHẤT import Qt) — 5 tab, song ngữ
├── engine.py               # Engine dịch (httpx + threading) — KHÔNG phụ thuộc Qt
├── config.example.json     # Mẫu cấu hình (KHÔNG chứa key) — copy thành config.json
├── requirements.txt        # httpx, PyQt6
├── run_tool.command        # Double-click mở app trên macOS
├── system_prompt.txt       # System prompt dịch (tự sinh / chỉnh tay)
├── tests/
│   └── test_engine.py      # Test engine headless (MockProvider, không cần mạng)
└── CLAUDE.md               # Ghi chú kiến trúc cho người phát triển
```

- **Tách lớp engine ↔ GUI bằng callback** (`emit(evt)`) nên `engine.py` test được headless, không import Qt.
- Thêm định dạng input mới = thêm nhánh trong `detect_format` + lớp `Doc` của `engine.py`, **không đụng lõi dịch**.

---

## Kiểm thử

Test engine chạy hoàn toàn **offline** (dùng `MockProvider`, không gọi mạng):

```bash
python3 tests/test_engine.py
```

Báo `PASS=… FAIL=0` nếu mọi thứ ổn (exit code 1 khi có lỗi). Luôn chạy lại sau khi sửa `engine.py`.
---

*Made with care for the game localization community.* — **PS5VietHoa**
