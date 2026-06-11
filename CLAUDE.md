# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Tổng quan

**KeyValue Game Localization AI Translator** — tool dịch file localization game **EN→VI** bằng AI.
Định dạng input ĐA-FORMAT (tự nhận diện): (1) `KEY=NỘI_DUNG` mỗi dòng (key/ID giữ nguyên, chỉ dịch phần sau `=`; dòng `#` là comment); (2) **Resident** (FF7 Rebirth `Resident_TxtRes`): dòng đầu = header ngôn ngữ (vd `US`), rồi từng block `$KEY` + 0..n dòng nội dung, mỗi dòng là 1 biến thể độc lập (dịch riêng). Xem `engine.py` `parse_doc`/`detect_format`.
Dùng API LLM (mặc định Claude qua trolllm, OpenAI-compatible). Tác giả: PS5VietHoa (Phước Lê & Mèo Mặt Căng).

Bản chính là app **PyQt6**:
- `engine.py` — engine dịch (httpx + threading + ThreadPoolExecutor), KHÔNG import Qt. Hỗ trợ 2 format API (OpenAI-compatible + Anthropic), dịch đa luồng, tự sinh system prompt, tự kiểm-tự sửa, resume.
- `app.py` — GUI PyQt6: 5 tab (API / System Prompt / Dịch / Xem trước / Hướng dẫn), trực quan hóa tiến độ realtime, **song ngữ Việt/English** (bộ chuyển ở header). Là nơi DUY NHẤT import PyQt6.
- `config.json` — cấu hình (provider, base_url, keys, model, batching...).
- `tests/test_engine.py` — test engine headless (MockProvider, không cần mạng).

## Lệnh thường dùng

```bash
# Chạy app PyQt6 (bản chính)
python3 app.py            # hoặc double-click run_tool.command (macOS)

# Test engine headless (KHÔNG cần mạng, dùng MockProvider) — luôn chạy sau khi sửa engine.py
python3 tests/test_engine.py

# Cài dependency (httpx cho engine, PyQt6 cho GUI)
pip install -r requirements.txt
```

Không có bước build/lint. Test = `tests/test_engine.py` (assert thuần, exit code 1 nếu fail).

## Kiến trúc

### Tách lớp engine ↔ GUI bằng callback (KHÔNG phải pyqtSignal)
Engine giao tiếp ra ngoài qua **một callback `emit(evt: dict)`** — nhờ vậy `engine.py` test được headless, không phụ thuộc Qt. `app.py` bọc callback bằng `EngineBridge(QObject)` để chuyển `evt` thành `pyqtSignal` (queued-connection → an toàn cross-thread). **Đừng import Qt vào engine.py.**

Các loại event: `progress`, `batch_init`, `batch` (state: queued/running/done/error/retry), `worker`, `log`, `stats`, `finished`. Payload là dict JSON-serializable.

### Provider abstraction (2 format API), mạng dùng httpx
`Provider` (base, giữ httpx client pooling + retry + map lỗi HTTP dùng chung) + 2 subclass chỉ override 4 hàm **thuần**:
- `OpenAIProvider`: `POST {base}/v1/chat/completions`, `Authorization: Bearer`, body `messages:[{system},{user}]` + `max_tokens`, parse `choices[0].message.content`, có `/v1/models`.
- `AnthropicProvider`: `POST {base}/v1/messages`, `x-api-key` + `anthropic-version: 2023-06-01`, body `system` riêng + `messages:[{user}]`, parse `content[0].text`, không có `/models`.
- **Mạng = httpx** (connection pooling + keep-alive + HTTP/2 nếu có gói `h2`; tự dùng certifi → không dính SSL CERTIFICATE_VERIFY_FAILED trên macOS). Client lazy, đóng ở `run_translation` finally + các hàm one-shot.
- **Chuẩn hóa base_url** (`_norm_base` + `_join_v1`): chỉ cần điền domain (vd `chat.trollllm.xyz`), tool tự thêm `/v1/...`, bỏ `/` thừa, gộp `/v1` sẵn có, và **nâng `http://`→`https://` cho host công khai** (giữ http cho localhost/LAN) — vì server LLM ép https, gọi http sẽ 301 và httpx đổi POST→GET làm hỏng request.

Map lỗi (`Provider._raise_for_status`): 429/rate/quota → `RateLimit` (cooldown 60s), 401/403 → `DeadKey` (loại key), 5xx/408 → `Transient` (cooldown 8s, retry).

### Threading
`app.py` chạy `engine.run_translation(cfg, emit, stop)` trong **một `OrchestratorThread(QThread)`**; bên trong engine vẫn dùng `ThreadPoolExecutor(max_workers=workers)`. **Stop = `threading.Event`** chia sẻ giữa UI và engine. Tác vụ API ngắn ở tab API (test connection, list models, gen prompt) chạy qua `FnThread` để không đơ UI.

### Trực quan hóa (tab Dịch)
`BatchGridWidget` (custom QWidget + QPainter) vẽ lưới ô màu từng lô — QPainter vì có thể hàng trăm/nghìn lô, update cục bộ. Kèm `StatCard`, bảng worker (`QTableWidget`), log coalesced (buffer + `QTimer` 120ms).

### Tab XEM TRƯỚC (bảng key/EN/VI) — TUYỆT ĐỐI không block UI
Bảng đối chiếu dùng **QTableView + `PreviewModel(QAbstractTableModel)` + `PreviewFilter(QSortFilterProxyModel)`** (ảo hóa — chỉ vẽ phần nhìn thấy). KHÔNG dùng QTableWidget: với file lớn (vài chục nghìn dòng) tạo item cho mọi ô làm **đơ UI vài giây**. Dữ liệu đọc/parse bằng `engine.build_preview_rows(src, out)` chạy trong **`FnThread` (nền)**, xong mới `model.set_rows()`.
- **Lazy load**: `PreviewModel` giữ toàn bộ `_rows` nhưng chỉ lộ `_loaded` hàng (chunk 250); `canFetchMore`/`fetchMore` nạp thêm khi cuộn → `set_rows` ~0ms kể cả file rất lớn.
- **Lọc/tìm**: `_filter_preview` gọi `model.load_all()` trước khi áp proxy filter (lazy chỉ lộ chunk đầu, không load hết thì lọc/tìm sẽ thiếu).
- Quy tắc chung: mọi thao tác đọc/parse file hoặc dựng bảng lớn phải off-UI-thread + ảo hóa + lazy.

## Định dạng dữ liệu & logic dịch
- Mỗi dòng `KEY=NỘI_DUNG`. Chỉ dịch phần **SAU** `=`. Bỏ qua dòng `#`, dòng rỗng, dòng `KEY=KEY`.
- **ĐA-FORMAT I/O** (`engine.py`, lớp `Doc`): lõi dịch CHỈ làm việc với `doc.pairs = [(uid, en)]` (uid DUY NHẤT) + `doc.serialize(vals)` (dựng lại ĐÚNG format gốc). `parse_doc(txt)` tự nhận diện qua `detect_format` (đếm dòng `^\$…` đứng riêng vs dòng có `=`). Ghi atomic bằng `write_doc(path, doc, vals)`. **Output là cùng format input** nên `load_progress`/`build_preview_rows` parse lại bằng `parse_doc` → uid khớp giữa src↔output.
  - **kv**: `uid = KEY`. payload = list dòng raw; serialize giữ dòng `#`/không-`=`, thay value cho key có trong `vals`.
  - **resident** (FF7 Rebirth): `uid = '$KEY#<chỉ_số_dòng>'` (KEY sạch `[A-Za-z0-9_$]`, không chứa `#`). payload = `(header, blocks)` với `blocks=[(key,[content_lines])]` giữ NGUYÊN để serialize tái tạo block. Mỗi dòng nội dung = 1 đơn vị dịch độc lập. **serialize ép mỗi đơn vị về đúng 1 dòng** (`vi.replace('\n',' ')`) vì cấu trúc block dựa trên ranh giới dòng — xuống dòng trong game dùng thẻ `<cf>`, KHÔNG dùng `\n` thật. File mẫu ~1.9MB: 22 487 key → 29 241 đơn vị; round-trip `serialize({})` khớp byte-for-byte với gốc.
  - Thêm format mới = thêm nhánh trong `detect_format` + `Doc.serialize` + `parse_doc`; KHÔNG đụng lõi `TranslationRun`. Có test ở `tests/test_engine.py` mục `[7]`.
- **GIỮ NGUYÊN bất biến**: `{biến}` (`RE_CURLY`), thẻ `<...>` (`RE_TAG`, bắt cả `<cf> <color=…> <button=…> <count=N>` của resident), `[REDACTED]` (`RE_REDACT`), `\n`, `\r`. `check_line` validate; dòng lỗi bị dịch lại (vòng tự-kiểm-tự-sửa, tối đa `rounds`).
- **Giao tiếp với LLM bằng JSON array**: gửi `[{id,en,placeholders}]` → nhận `[{id,vi}]` (`build_user_prompt` / `parse_json_array`). Payload JSON nằm **sau `\n\n` cuối** của user prompt (parse lại dùng `rsplit('\n\n',1)[-1]`, KHÔNG dùng `rfind('[')` vì placeholders chứa `[`).
- **Resume / ghi nhớ mốc đã dịch** (`load_progress`, `resume_status`): key xong append `<out>.done.txt`, output ghi **atomic** (`.tmp`→`os.replace`) sau mỗi lô. **File output là nguồn chân lý**: chỉ coi key "đã xong" khi output thật sự có dòng đó (xóa output mà còn `done.txt` vẫn dịch lại đúng). App lưu `src/out` vào `config.json` khi bấm Bắt đầu để mở lại tự điền.
- **Chọn model & tự đổi model** (`auto_switch`): TẮT (mặc định) → `models=[model_đã_chọn]` (rate-limit thì chờ rồi thử lại cùng model); BẬT → thêm model dự phòng để `pick_combo` nhảy sang khi 429/lỗi.
- **Tự sinh system prompt**: `gen_system_prompt(provider, key, model, sample, game_name, tone, note)` — lấy mẫu rải đều bằng `sample_for_prompt`, nhét tên game vào meta-prompt.

## Song ngữ (i18n) trong app.py
- **Mọi chuỗi UI tĩnh phải qua `self.t('key', *args)`** (đọc từ dict `TR` ở đầu file), KHÔNG hardcode. Thêm chuỗi mới = thêm entry `{'vi':..., 'en':...}` vào `TR`. Chuỗi có `%s/%d` → gọi kèm args (`self.t('st_models_ok', n)`). Tên tham số kỹ thuật (`max_tokens`, `temperature`) cố tình giữ literal.
- **Nội dung tab Hướng dẫn** nằm trong `_guide_data(lang)` (song ngữ), KHÔNG trong các hàm `_guide_*` (chúng chỉ dựng widget từ data truyền vào).
- **Đổi ngôn ngữ = rebuild**: `_set_lang` → `_snapshot_ui()` (lưu mọi ô nhập) → đổi `self.lang` → `_persist_lang()` (ghi `lang` vào config.json) → `_build_central()` (dựng lại header+5 tab) → `_restore_ui()`. Bridge wiring giữ ở `__init__` (slot trỏ `self.<widget>` nên tự đúng sau rebuild — đừng tạo lại bridge). Chặn đổi ngôn ngữ khi đang dịch (khóa `cb_lang`).
- Log do engine phát vẫn tiếng Việt (engine.py không i18n) — chấp nhận, ngoài phạm vi UI.

## Gotchas
- Sửa **logic dịch lõi** → sửa trong `engine.py`; chạy `python3 tests/test_engine.py` ngay sau đó (verify headless, không phụ thuộc trạng thái API trolllm).
- **KHÔNG dùng emoji trong UI PyQt6** (yêu cầu của chủ dự án) — trạng thái thể hiện bằng màu + chữ.
- Test mock đọc payload bằng `rsplit('\n\n',1)[-1]`.
- **Smoke test GUI phải trỏ `app.CONFIG_PATH` sang file tạm** trước khi tạo `MainWindow` — đổi ngôn ngữ / Lưu cấu hình sẽ GHI ĐÈ `config.json` thật (mất API key). Đừng dựng MainWindow với config thật khi test.

## File nhạy cảm / không commit
`keys.txt`, `keys_trollllm.txt`, `config.json` (chứa API key thật), `tk gmail.txt` — **không đưa ra ngoài, không commit, không log**.
