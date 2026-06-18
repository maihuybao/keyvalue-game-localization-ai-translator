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

**Tự GIẢM `max_tokens` khi 400 (2 loại lỗi, `_post` chỉ xử lý status 400):** trần UI cho `max_tokens` là 1.000.000 nhưng model có giới hạn thật → đặt cao gây 400 khi DỊCH. Hai nhánh nối tiếp:
1. **Vượt trần OUTPUT** (`_max_tokens_cap_from_error`): lỗi `"max_tokens: 1000000 > 128000, which is the maximum allowed number of output tokens"` (có `max_tokens`/`output token`) → `parse_max_tokens_cap` đọc trần (regex `>\s*(\d{3,})`, `at most (\d+)`, `(?:max|context|window|limit)…(\d+)`) → kẹp `max_tokens` = trần đó.
2. **Vượt CONTEXT WINDOW** (`_context_overflow_cap_from_error`, KHÁC loại 1): sau khi loại 1 kẹp `max_tokens=128000`, nhưng cửa sổ ngữ cảnh router (vd **9Router**) cũng = 128000 → `input + max_tokens` vượt → `400 "maximum context length is 128000 … (N in messages, M in completion)"`. `_CONTEXT_ERR_RE` nhận diện → đọc trần ngữ cảnh → **kẹp `max_tokens = trần//2`** (chừa nửa cửa sổ cho input). CHỈ giảm khi `new < max_tokens` hiện tại; nếu `max_tokens` đã nhỏ mà vẫn vượt → do INPUT quá to (giảm `maxchars`), KHÔNG đụng.

Cả hai raise `Transient('…đã giảm…')` để `translate_batch` thử lại (provider DÙNG CHUNG → cả run tự sửa); `test_connection` bắt `'đã giảm' in str(e)` → thử lại 1 lần + báo "đã tự giảm max_tokens xuống N". **Khuyến nghị: dịch chỉ cần `max_tokens` nhỏ (vài nghìn); đặt = trần model là thừa và gây lỗi (2)**. Test: `tests/test_engine.py` mục `[12]`.

**Debug API ra console** (`Provider.debug`, cờ `debug` trong config + checkbox "Debug: in lỗi API ra console" ở tab API, mặc định BẬT; `make_provider` truyền vào): khi BẬT, mỗi lần gọi API lỗi sẽ in ra **stderr** qua `_debug_dump(url, body, detail)` — URL + `model` + mã HTTP + **nguyên văn API trả về** (cắt `DEBUG_MAX=4000`). Bốn trường hợp bắt trong `_post`/`call`: network error, HTTP ≥400, `no_json` (router trả SSE/HTML), parse/`no_content` (200 + JSON sai cấu trúc — in cả JSON). **TUYỆT ĐỐI không in header/API key** (chỉ truyền `url`+`body`, không truyền `headers`). Test ở `tests/test_engine.py` mục `[10]` (tiêm `_client` giả, bắt stderr, assert key KHÔNG lộ).

**Context window 1M (`context_1m`, mặc định TẮT):** checkbox "Context 1M (Claude beta)" ở tab API → `build_anthropic_beta(cfg)` dựng chuỗi `anthropic-beta` (nối `,`), `make_provider` truyền vào `Provider(anthropic_beta=…)`; `_with_beta(headers)` gắn header `anthropic-beta: context-1m-2025-08-07` cho CẢ 2 provider (router OpenAI-compatible proxy Claude thường chuyển tiếp). ⚠️ Theo tài liệu Claude API: model HIỆN ĐẠI (Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5) **đã có 1M context mặc định, không cần header**; beta này chỉ cần cho **Claude Sonnet 4 cũ** (`claude-sonnet-4-20250514`, 200K→1M). Muốn TẬN DỤNG cửa sổ lớn = tăng `maxlines`/`maxchars` (gửi lô to hơn), không phải chỉ bật header. Header KHÔNG nhạy cảm và debug chỉ in url+body nên không lộ. Cũng nhận `anthropic_beta` (chuỗi thô) trong config để thêm beta khác. Test: `tests/test_engine.py` mục `[13]`.

**Tương thích router/model:** OpenAI body luôn gửi `stream: false` — nhiều router (vd 9Router `localhost:20128`) MẶC ĐỊNH trả SSE (`text/event-stream`) làm `r.json()` hỏng (`no_json`). `temperature` chỉ gửi khi khác `None`: model suy luận (gpt-5/codex/o-series) trả `400 Unsupported parameter: 'temperature'`. Cờ `send_temperature` (config + checkbox "temperature:" ở tab API, mặc định bật) → `make_provider` đặt `temperature=None` để `build_body` bỏ field. `test_connection` nhận diện lỗi này và gợi ý bỏ tích.

### Threading
`app.py` chạy `engine.run_translation(cfg, emit, stop)` trong **một `OrchestratorThread(QThread)`**; bên trong engine vẫn dùng `ThreadPoolExecutor(max_workers=workers)`. **Stop = `threading.Event`** chia sẻ giữa UI và engine. Tác vụ API ngắn ở tab API (test connection, list models, gen prompt) chạy qua `FnThread` để không đơ UI.

### Dịch cả thư mục (folder mode)
Tab DỊCH có công tắc **File đơn / Cả thư mục** (`rb_mode_file`/`rb_mode_folder`). Chế độ thư mục: `src`/`out` là THƯ MỤC, thêm ô **đuôi file** (`ed_ext`, cách nhau dấu cách/phẩy; trống = mọi file). `_gather_cfg` thêm `mode` (`'file'`/`'folder'`) + `exts` (chuỗi thô); lưu vào `config.json`. `OrchestratorThread.run` branch: `mode=='folder'` → `engine.run_folder_translation`, ngược lại `run_translation`.
- **`run_folder_translation(cfg, emit, stop)`**: `list_folder_files(folder, exts)` (đệ quy, sort, bỏ file/thư mục ẩn + artifact `.done.txt`/`.tmp`) → mỗi file là **một `TranslationRun`** với `src/out` per-file (giữ NGUYÊN cây thư mục dưới `out`), **dùng CHUNG 1 provider** (truyền `provider=` vào `TranslationRun.__init__` → tái dùng pool httpx, KHÔNG tạo lại mỗi file). Resume per-file dùng lại nguyên cơ chế (output từng file là nguồn chân lý).
- **finished từng file bị "nuốt"**: `file_emit` chặn event `finished` của mỗi `TranslationRun` (gom vào `agg`), gắn tên file vào `log`, và chỉ phát **MỘT** `finished` tổng kết ở cuối. Event mới: `folder_init {n_files,exts}`, `folder_file {index,total,name,state:start|done,...}` → cập nhật `lbl_folder` (tiến độ cấp thư mục); thanh/lưới/thẻ vẫn là tiến độ FILE hiện tại (reset mỗi file qua `batch_init`).
- **UI off-thread**: `_update_resume` ở chế độ thư mục gọi `folder_overview` (chỉ `os.walk` + `os.path.isfile`, KHÔNG đọc nội dung) để đếm nhanh số file khớp/đã có kết quả. `default_out_folder` gợi ý `<tên>_vi`. Test: `tests/test_engine.py` mục `[8]` (monkeypatch `E.make_provider` → MockProvider).

### Trực quan hóa (tab Dịch)
`BatchGridWidget` (custom QWidget + QPainter) vẽ lưới ô màu từng lô — QPainter vì có thể hàng trăm/nghìn lô, update cục bộ. Kèm `StatCard`, bảng worker (`QTableWidget`), log coalesced (buffer + `QTimer` 120ms).

### Tab XEM TRƯỚC (bảng key/EN/VI) — TUYỆT ĐỐI không block UI
Bảng đối chiếu dùng **QTableView + `PreviewModel(QAbstractTableModel)` + `PreviewFilter(QSortFilterProxyModel)`** (ảo hóa — chỉ vẽ phần nhìn thấy). KHÔNG dùng QTableWidget: với file lớn (vài chục nghìn dòng) tạo item cho mọi ô làm **đơ UI vài giây**. Dữ liệu đọc/parse bằng `engine.build_preview_rows(src, out, byte_limit)` chạy trong **`FnThread` (nền)**, xong mới `model.set_rows()`.
- **5 cột**: `(key, en, vi, status, en_bytes, vi_bytes)` — 2 cột cuối **so sánh byte UTF-8** gốc/dịch (`columnCount=5`). Ô **Byte VI tô đỏ `_PV_OVER`** khi `vi_bytes > en_bytes` (bản dịch VƯỢT byte gốc) — LUÔN hiển thị, độc lập với việc bật/tắt ép byte. `data()` căn phải 2 cột byte. Filter có thêm cờ `only_over` (checkbox "Chỉ hiện vượt byte"). `pv_summary` thêm "vượt byte %d".
- **Lazy load**: `PreviewModel` giữ toàn bộ `_rows` nhưng chỉ lộ `_loaded` hàng (chunk 250); `canFetchMore`/`fetchMore` nạp thêm khi cuộn → `set_rows` ~0ms kể cả file rất lớn.
- **Lọc/tìm**: `_filter_preview` gọi `model.load_all()` trước khi áp proxy filter (lazy chỉ lộ chunk đầu, không load hết thì lọc/tìm sẽ thiếu).
- Quy tắc chung: mọi thao tác đọc/parse file hoặc dựng bảng lớn phải off-UI-thread + ảo hóa + lazy.

## Định dạng dữ liệu & logic dịch
- Mỗi dòng `KEY=NỘI_DUNG`. Chỉ dịch phần **SAU** `=`. Bỏ qua dòng `#`, dòng rỗng, dòng `KEY=KEY`.
- **ĐA-FORMAT I/O** (`engine.py`, lớp `Doc`): lõi dịch CHỈ làm việc với `doc.pairs = [(uid, en)]` (uid DUY NHẤT) + `doc.serialize(vals)` (dựng lại ĐÚNG format gốc). `parse_doc(txt)` tự nhận diện qua `detect_format` (đếm dòng `^\$…` đứng riêng vs dòng có `=`). Ghi atomic bằng `write_doc(path, doc, vals)`. **Output là cùng format input** nên `load_progress`/`build_preview_rows` parse lại bằng `parse_doc` → uid khớp giữa src↔output.
  - **kv**: `uid = KEY`. payload = list dòng raw; serialize giữ dòng `#`/không-`=`, thay value cho key có trong `vals`.
  - **resident** (FF7 Rebirth): `uid = '$KEY#<chỉ_số_dòng>'` (KEY sạch `[A-Za-z0-9_$]`, không chứa `#`). payload = `(header, blocks)` với `blocks=[(key,[content_lines])]` giữ NGUYÊN để serialize tái tạo block. Mỗi dòng nội dung = 1 đơn vị dịch độc lập. **serialize ép mỗi đơn vị về đúng 1 dòng** (`vi.replace('\n',' ')`) vì cấu trúc block dựa trên ranh giới dòng — xuống dòng trong game dùng thẻ `<cf>`, KHÔNG dùng `\n` thật. File mẫu ~1.9MB: 22 487 key → 29 241 đơn vị; round-trip `serialize({})` khớp byte-for-byte với gốc.
  - Thêm format mới = thêm nhánh trong `detect_format` + `Doc.serialize` + `parse_doc`; KHÔNG đụng lõi `TranslationRun`. Có test ở `tests/test_engine.py` mục `[7]`.
- **Value có thể trải NHIỀU DÒNG vật lý (chỉ kv)**: dòng sau `KEY=...` không có `=` và không bắt đầu `#` → **ghép vào value của KEY trước** (cách nhau bằng `\n`). Dòng rỗng giữa dòng value → giữ `\n`. Comment phá vỡ continuation. `Doc.serialize` (kv) ghi ĐÚNG số dòng vật lý (an toàn `\r` → space, strip `\n` thừa cuối). `check_line` đếm newline **thật** (`'\n'` 1 ký tự, KHÔNG phải escape `'\\n'` 2 ký tự) để khớp với parse. Ví dụ: `TUTORIAL=Press <button=X> now\nto continue` → file output giữ nguyên 2 dòng vật lý, AI dịch phải trả cả `\n` trong value. Test: `tests/test_engine.py` mục `[14]`.
- **GIỮ NGUYÊN bất biến**: `{biến}` (`RE_CURLY`), thẻ `<...>` (`RE_TAG`, bắt cả `<cf> <color=…> <button=…> <count=N>` của resident), `[REDACTED]` (`RE_REDACT`), `\n`, `\r`. `check_line` validate; dòng lỗi bị dịch lại (vòng tự-kiểm-tự-sửa, tối đa `rounds`).
- **Ngân sách BYTE (`byte_limit`, mặc định TẮT)**: ép số byte UTF-8 bản dịch **không vượt câu gốc EN** (buffer game = đúng ô chữ gốc). `utf8_len(s)=len(s.encode('utf-8'))`. Tickbox "Giới hạn byte ≤ bản gốc" ở **card model tab DỊCH** (`cb_byte_limit`) → `_gather_cfg` thêm `byte_limit`. Cơ chế = **chính tickbox là LỰA CHỌN**: BẬT → engine gửi `max_bytes=utf8_len(en)` cho mỗi item (`build_user_prompt` thêm field `max_bytes` + hướng dẫn rút gọn khi item có budget) VÀ `check_line(en, vi, byte_limit=True)` gắn lý do `vượt_byte(+NB)` → dòng vượt bị coi "nghi lỗi" → **dịch lại qua vòng tự-sửa** (giống lệch placeholder); TẮT → chỉ XEM đối chiếu byte + tô đỏ ở tab Xem trước (KHÔNG dịch lại). ⚠️ Tiếng Việt có dấu tốn 2-3 byte/ký tự nên NHIỀU dòng có thể **không thể vừa** → sau `rounds` vẫn báo "còn N dòng nghi lỗi" (chấp nhận, best-effort). Engine là TRỌNG TÀI byte (không tin AI tự đếm) — y như tool `rdr2-vuotbyte-fixer`. Test: `tests/test_engine.py` mục `[11]`.
- **Giao tiếp với LLM bằng JSON array**: gửi `[{id,en,placeholders}]` → nhận `[{id,vi}]` (`build_user_prompt` / `parse_json_array`). Payload JSON nằm **sau `\n\n` cuối** của user prompt (parse lại dùng `rsplit('\n\n',1)[-1]`, KHÔNG dùng `rfind('[')` vì placeholders chứa `[`).
- **Resume / ghi nhớ mốc đã dịch** (`load_progress`, `resume_status`): key xong append `<out>.done.txt`, output ghi **atomic** (`.tmp`→`os.replace`) sau mỗi lô. **File output là nguồn chân lý**: chỉ coi key "đã xong" khi output thật sự có dòng đó (xóa output mà còn `done.txt` vẫn dịch lại đúng). App lưu `src/out` vào `config.json` khi bấm Bắt đầu để mở lại tự điền.
- **Chọn model (mặc định + override theo tab)**: tab API = **model mặc định** (`model`); tab System Prompt (`model_prompt`) và tab Dịch (`model_translate`) có combobox riêng, mục đầu **'(Theo mặc định)'** = `''` trong config → BÁM theo `model`. `_gather_cfg`: `eff_tr = model_translate or model`; danh sách model fetch đồng bộ vào CẢ 3 combobox (`_fill_model_combos`; combo phụ tạo bằng `_make_model_combo`, đọc bằng `_resolve_model` → `''` nếu đang '(Theo mặc định)'). Dịch dùng `models` (dẫn đầu `eff_tr`); sinh prompt dùng `model_prompt or model`; **test kết nối / fetch dùng `model` mặc định** (`_provider_from_ui`).
- **Tự đổi model** (`auto_switch`): TẮT (mặc định) → `models=[eff_tr]` (rate-limit thì chờ rồi thử lại cùng model); BẬT → thêm toàn bộ danh sách làm model dự phòng để `pick_combo` nhảy sang khi 429/lỗi.
- **Giới hạn ô nhập (tab API)**: `max_tokens` ≤ 1.000.000, `workers` (số luồng) ≤ 10000, `maxlines` (dòng/lô) ≤ 1000 — chỉ là trần UI, engine không tự chặn; đặt cao bất thường (vd 10000 luồng) là lựa chọn của người dùng.
- **Tự sinh system prompt**: `gen_system_prompt(provider, key, model, sample, game_name, tone, note, gen_max_tokens=16384)` — lấy mẫu rải đều bằng `sample_for_prompt`, nhét tên game vào meta-prompt. **Trần output = 16384** (HẠ xuống chỉ khi `max_tokens` hiện tại lớn hơn): ĐỦ RỘNG cho prompt giàu (glossary lớn như FF7 Rebirth ~6k token) để KHÔNG bị cắt ngang, nhưng vẫn chặn việc người dùng đặt `max_tokens` rất cao để DỊCH (tới 1.000.000) khiến API từ chối "max_tokens quá lớn". (16384 = trần output GPT-4o, an toàn với Claude tới 64k.) ⚠️ Trần này TỪNG đặt 4096 → prompt FF7 bị **cắt ngang** (`finish_reason=length`); đã nâng lên 16384. Input đã được `sample_for_prompt` chặn (≤120 dòng/6000 ký tự) nên chỉ MẪU nhỏ được gửi.
- **Phát hiện CẮT NGANG (truncation)**: `Provider.is_truncated(j)` (OpenAI `choices[0].finish_reason=='length'`; Anthropic `stop_reason=='max_tokens'`) → `call()` đặt `self.last_truncated` + in cảnh báo console (khi debug). Tab System Prompt: `_gen_prompt` giữ `self._gen_prov`, `_on_gen` kiểm `last_truncated` → hiện cảnh báo "TĂNG max_tokens, Tạo lại" nhưng VẪN điền prompt (không mất nội dung).
- **Đếm/cảnh báo token**: `estimate_tokens(text)` (≈ ký tự/4, không cần tokenizer ngoài) + `sample_stats(text)` → `{lines,chars,tokens,sample_tokens}` chạy ở `FnThread` để tab System Prompt hiện "tổng token + token mẫu gửi đi" (`lbl_sample`, cập nhật theo `ed_sample.textChanged`, bỏ kết quả cũ qua `_sample_path`). `is_token_limit_error(msg)` nhận diện lỗi vượt token/`max_tokens` → `test_connection` và `_on_gen` đổi sang thông báo "GIẢM max_tokens".

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
