#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
#  engine.py  —  KeyValue Game Localization AI Translator: engine dịch file KEY=text (EN -> VI).
#                KHÔNG phụ thuộc Qt.
#
#  - Mạng dùng httpx (connection pooling + keep-alive + HTTP/2 nếu có) -> nhanh hơn urllib
#    nhiều khi gọi hàng trăm lô (tái dùng TLS, không handshake lại mỗi request).
#    httpx tự dùng certifi -> không dính CERTIFICATE_VERIFY_FAILED trên macOS.
#  - Hỗ trợ 2 format API: OpenAI-compatible (/chat/completions) & Anthropic (/v1/messages).
#  - Dịch ĐA LUỒNG (ThreadPoolExecutor): chia lô, gửi JSON array [{id,en}] -> [{id,vi}].
#  - Tự kiểm & tự sửa placeholder, resume qua <out>.done.txt, xoay (model,key) + cooldown.
#  - Tự sinh system prompt từ tên game + mẫu text EN.
#
#  Giao tiếp với GUI qua MỘT callback emit(evt: dict). Không import PyQt -> test headless được.
#  Lớp GUI (app.py) bọc emit bằng pyqtSignal.
# ============================================================================
import os, sys, json, time, re, threading
from concurrent.futures import ThreadPoolExecutor
import httpx

DEBUG_MAX = 4000   # số ký tự tối đa của response in ra console khi debug (đủ rộng để soi lỗi API)
CONTEXT_1M_BETA = 'context-1m-2025-08-07'   # header beta mở context window 1M cho Claude (Sonnet 4 cũ; model mới đã 1M sẵn)

# ============================== PROMPT MẶC ĐỊNH ==============================
UNIVERSAL_RULES = (
    "Bạn là chuyên gia bản địa hóa game sang TIẾNG VIỆT tự nhiên, chuẩn game AAA.\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- Bạn nhận một JSON array các mục [{\"id\":int,\"en\":\"...\"}]. Dịch phần \"en\" sang tiếng Việt.\n"
    "- GIỮ NGUYÊN tuyệt đối: {biến} {0} \\n \\r thẻ HTML <...> </...> [REDACTED] và mọi placeholder/ký hiệu điều khiển.\n"
    "  Số lượng và vị trí placeholder trong bản dịch PHẢI khớp bản gốc.\n"
    "- Dịch tự nhiên, đúng nghĩa, hợp văn cảnh; KHÔNG dịch máy từng từ.\n"
    "- Mục \"en\" rỗng/chỉ ký hiệu/mã -> giữ NGUYÊN.\n"
    "- Nếu `en` chứa ký tự xuống dòng thật (\\n), bản dịch `vi` PHẢI có ĐÚNG cùng số \\n ở cùng vị trí tương đối (xuống dòng tương ứng từng dòng trong game UI).\n"
    "- KHÔNG giải thích, KHÔNG chú thích."
)
OUTPUT_REMINDER = (
    "=== ĐỊNH DẠNG TRẢ LỜI (BẮT BUỘC) ===\n"
    "CHỈ trả về một JSON array, KHÔNG markdown, KHÔNG ```json, KHÔNG giải thích:\n"
    "[{\"id\":0,\"vi\":\"...\"},{\"id\":1,\"vi\":\"...\"}]\n"
    "Đúng số mục, mỗi id một bản dịch."
)
GEN_META_SYS = (
    "Bạn là chuyên gia tạo SYSTEM PROMPT để bản địa hóa game sang tiếng Việt. "
    "Bạn nhận TÊN GAME và một mẫu text game (tiếng Anh, định dạng ID=nội_dung), rồi viết ra một "
    "system prompt tiếng Việt HOÀN CHỈNH để một AI khác dùng dịch toàn bộ game này thật nhất quán."
)
GEN_META_USER = (
    "Hãy phân tích rồi VIẾT một system prompt tiếng Việt đầy đủ, gồm:\n"
    "1. BỐI CẢNH GAME: đoán thể loại, không khí, tone phù hợp (dựa vào tên game + mẫu text).\n"
    "2. GLOSSARY: tên riêng/nhân vật/địa danh GIỮ NGUYÊN; thuật ngữ gameplay DỊCH THỐNG NHẤT (liệt kê EN -> VI).\n"
    "3. XƯNG HÔ & VĂN PHONG theo loại string (UI ngắn gọn; thoại tự nhiên; lore trang trọng...).\n"
    "4. QUY TẮC KỸ THUẬT: GIỮ NGUYÊN mọi {biến} <thẻ> \\n \\r [REDACTED]; chuỗi UI HOA giữ HOA; "
    "mục rỗng/ký hiệu giữ nguyên.\n\n"
    "CHỈ trả về NỘI DUNG system prompt (tiếng Việt), KHÔNG mở đầu, KHÔNG ```.\n"
)
TONES = {
    'Tự động (theo nội dung)': '',
    'Hành động / Bắn súng': 'Văn phong mạnh mẽ, gọn, kịch tính; thoại dứt khoát.',
    'Kinh dị / Hồi hộp': 'Văn phong rùng rợn, căng thẳng, u ám; tạo không khí sợ hãi.',
    'Nhập vai RPG / Giả tưởng': 'Văn phong sử thi, trang trọng, đậm chất giả tưởng; tên kỹ năng/vật phẩm nhất quán.',
    'Phiêu lưu / Giải đố': 'Văn phong nhẹ nhàng, tò mò, dẫn dắt khám phá.',
    'Anime / JRPG': 'Văn phong cảm xúc, trẻ trung, giàu biểu cảm; giữ sắc thái từng nhân vật.',
    'Hài hước': 'Văn phong vui nhộn, dí dỏm, chơi chữ hợp lý.',
    'Trinh thám / Hồ sơ mật': 'Văn phong lạnh, chính xác, hành chính, bí ẩn.',
    'Khoa học viễn tưởng': 'Văn phong hiện đại, chính xác, đậm chất công nghệ/khoa học.',
    'Thể thao / Đua xe': 'Văn phong nhanh, năng động, gọn rõ.',
}

# ============================== HÀM THUẦN (PURE) ==============================
RE_CURLY = re.compile(r'\{[^{}]*\}'); RE_TAG = re.compile(r'</?[a-zA-Z][^>]*>|<>')  # '<>' = tag rỗng (resident)
RE_REDACT = re.compile(r'\[[A-Z0-9 _\-]{2,}\]')
_PH_RE = re.compile(r'<[^>]*>|\{[^}]*\}|%[sdfSDF]|\\[nrt]')   # '<[^>]*>' bắt cả '<>' để gợi ý cho AI

def read_text(p):
    return open(p, encoding='utf-8-sig').read() if (p and os.path.isfile(p)) else ''   # isfile: path thư mục -> '' (không crash)

def utf8_len(s):
    """Số byte UTF-8 của chuỗi (buffer game đo bằng byte, không phải ký tự).
    Ký tự tiếng Việt có dấu tốn 2-3 byte; ASCII chỉ 1 byte -> bản dịch VI thường DÀI byte hơn EN."""
    return len((s or '').encode('utf-8'))

def extract_placeholders(text):
    seen = []
    for m in _PH_RE.findall(text):
        if m not in seen: seen.append(m)
    return seen

def parse_pairs_text(txt):
    """Mỗi dòng KEY=VALUE. Value có thể trải NHIỀU DÒNG vật lý: dòng tiếp theo KHÔNG có '=' và
    KHÔNG bắt đầu bằng '#' thì được nối vào value của KEY trước đó (cách nhau bằng '\n').
    Dòng rỗng trong value được giữ (thêm '\n'). Comment phá vỡ continuation.
    Ví dụ: 'K=A\\nB=C\\n  D' -> pairs=[('K','A\\n  D'), ('B','C')],  raw=[3 dòng]."""
    raw = txt.split('\n')
    if raw and raw[-1] == '': raw = raw[:-1]
    pairs = []
    pending_key = None        # KEY đang chờ ghép dòng tiếp theo
    pending_value = None
    for ln in raw:
        if not ln:
            if pending_key is not None:
                pending_value += '\n'                           # dòng rỗng trong value -> giữ \n
                pairs[-1] = (pending_key, pending_value)        # cập nhật tuple (tuple là bất biến)
            continue
        if ln.lstrip().startswith('#'):
            pending_key = None                                   # comment phá vỡ continuation
            continue
        if '=' in ln:
            k, v = ln.split('=', 1)
            pairs.append((k, v))
            pending_key, pending_value = k, v
            continue
        if pending_key is not None:                              # dòng thừa -> nối vào value
            pending_value += '\n' + ln
            pairs[-1] = (pending_key, pending_value)
        # else: dòng thừa không thuộc KEY nào (chưa từng có KEY) -> bỏ qua
    return raw, pairs

# ===================== ĐA-FORMAT I/O (KEY=VALUE  &  Resident $KEY-block) =====================
# Lõi gốc chỉ hiểu 'kv' (mỗi dòng KEY=VALUE). Thêm 'resident' (FF7 Rebirth Resident_TxtRes):
#   dòng đầu = header ngôn ngữ (vd 'US'); rồi từng block:  $KEY  +  0..n dòng nội dung,
#   mỗi dòng nội dung là 1 BIẾN THỂ độc lập (tên / mạo từ / số ít / số nhiều) -> DỊCH RIÊNG.
#   Bất biến vẫn là thẻ <...> (RE_TAG). Không có '=' phân tách -> không nạp thẳng vào parser KV.
# Trừu tượng chung: Doc.pairs = [(uid, en)] với uid DUY NHẤT; Doc.serialize(vals) dựng lại ĐÚNG format.
#   - kv:       uid = KEY (giữ NGUYÊN hành vi cũ; KEY trùng -> value cuối thắng).
#   - resident: uid = '<$KEY>#<chỉ_số_dòng>'  (KEY sạch [A-Za-z0-9_$], không chứa '#').
RE_RKEY = re.compile(r'^\$(?=[^\n]*[A-Za-z])[^\s=]+$')   # dòng KEY resident: '$' + có chữ cái, không space/'='

def detect_format(txt):
    """Đoán format từ nội dung: 'resident' nếu có >=3 dòng KEY đứng riêng và lấn át dòng KEY=VALUE."""
    n_key = n_kv = 0
    for ln in txt.split('\n'):
        if not ln or ln.lstrip().startswith('#'): continue
        if RE_RKEY.match(ln): n_key += 1
        elif '=' in ln: n_kv += 1
    return 'resident' if (n_key >= 3 and n_key >= n_kv) else 'kv'

class Doc:
    """Tài liệu locale đa-format. pairs=[(uid,en)] cho lõi dịch; serialize(vals) dựng lại đúng format gốc."""
    def __init__(self, fmt, payload, pairs):
        self.fmt = fmt; self.payload = payload; self.pairs = pairs

    def serialize(self, vals):
        if self.fmt == 'resident':
            header, blocks = self.payload
            out = list(header)
            for key, contents in blocks:
                out.append(key)
                for i, c in enumerate(contents):
                    v = vals.get('%s#%d' % (key, i), c)
                    out.append(v.replace('\r', ' ').replace('\n', ' '))   # mỗi đơn vị PHẢI đúng 1 dòng
            return '\n'.join(out) + '\n'
        out = []                                  # kv: giữ dòng #/không-phải-KEY=VALUE; thay value theo vals
        for ln in self.payload:
            if ln and not ln.lstrip().startswith('#') and '=' in ln:
                k = ln.split('=', 1)[0]
                if k in vals:
                    # vals[k] có thể chứa '\n' thật (value gốc nhiều dòng vật lý) ->
                    # ghi ĐÚNG số dòng vật lý. An toàn \r (thay bằng space), strip \n thừa cuối.
                    vi = vals[k].replace('\r', ' ').rstrip('\n')
                    out.append('%s=%s' % (k, vi))
                    continue
            out.append(ln)
        return '\n'.join(out) + '\n'

def _parse_resident(txt):
    txt = txt.lstrip('﻿')
    lines = txt.split('\n')
    if lines and lines[-1] == '': lines = lines[:-1]   # bỏ dòng rỗng cuối do '\n' kết file
    first = next((i for i, l in enumerate(lines) if RE_RKEY.match(l)), len(lines))
    header = lines[:first]
    blocks = []                                        # [(key, [content_lines])] — giữ NGUYÊN để serialize lại
    cur = None
    for l in lines[first:]:
        if RE_RKEY.match(l):
            cur = []; blocks.append((l, cur))
        else:
            if cur is None: cur = []; blocks.append(('', cur))   # phòng hờ (không xảy ra với file hợp lệ)
            cur.append(l)
    pairs = [('%s#%d' % (key, i), c) for key, contents in blocks for i, c in enumerate(contents)]
    return Doc('resident', (header, blocks), pairs)

def parse_doc(txt):
    """Đọc text -> Doc (tự nhận diện format). Lõi engine chỉ làm việc với Doc.pairs + Doc.serialize."""
    if detect_format(txt) == 'resident':
        return _parse_resident(txt)
    raw, pairs = parse_pairs_text(txt)
    return Doc('kv', raw, pairs)

def write_doc(path, doc, vals):
    """Ghi atomic (.tmp -> os.replace) theo đúng format của doc."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as w:
        w.write(doc.serialize(vals))
    os.replace(tmp, path)

def check_line(eng, vi, byte_limit=False):
    """Trả về list lý do lỗi (rỗng nếu OK).
    byte_limit=True -> thêm luật NGÂN SÁCH BYTE: bản dịch không được vượt số byte UTF-8 của dòng gốc EN
    (buffer game đo bằng byte). Dòng vượt bị coi là 'nghi lỗi' -> dịch lại ở vòng tự-sửa."""
    if not vi.strip(): return ['rỗng']
    r = []
    if '```' in vi: r.append('có_```')
    for nm, pat in (('{biến}', RE_CURLY), ('thẻ', RE_TAG), ('[..]', RE_REDACT)):
        if sorted(pat.findall(eng)) != sorted(pat.findall(vi)): r.append('lệch_' + nm)
    if eng.count('\n') != vi.count('\n'): r.append('lệch_\\n')   # đếm newline THẬT (1 ký tự)
    if vi.strip() == eng.strip() and len(eng) > 30 and ' ' in eng.strip(): r.append('chưa_dịch?')
    if byte_limit:
        over = utf8_len(vi) - utf8_len(eng)
        if over > 0: r.append('vượt_byte(+%dB)' % over)
    return r

def make_batches(items, maxlines, maxchars):
    b, cur, ch = [], [], 0
    for it in items:
        n = len(it['en']) + 12
        if cur and (len(cur) >= maxlines or ch + n > maxchars): b.append(cur); cur, ch = [], 0
        cur.append(it); ch += n
    if cur: b.append(cur)
    return b

def build_user_prompt(items):
    payload = []
    has_budget = False
    for it in items:
        obj = {'id': it['id'], 'en': it['en']}
        ph = it.get('placeholders')
        if ph: obj['placeholders'] = ph
        mb = it.get('max_bytes')
        if mb is not None:
            obj['max_bytes'] = mb; has_budget = True
        payload.append(obj)
    rules = ("Dịch các mục sau sang tiếng Việt theo ĐÚNG quy tắc trong system prompt.\n"
             "- `placeholders` (nếu có) = token BẮT BUỘC giữ NGUYÊN, đúng vị trí trong `vi`.\n")
    if has_budget:
        rules += ("- `max_bytes` (nếu có) = số byte UTF-8 TỐI ĐA cho bản dịch `vi` (giới hạn CỨNG, KHÔNG vượt). "
                  "Ký tự tiếng Việt có dấu tốn 2-3 byte/ký tự, chữ ASCII chỉ 1 byte -> hãy dịch NGẮN GỌN, "
                  "bỏ từ thừa, ưu tiên từ ít dấu để VỪA ngân sách mà vẫn đúng nghĩa.\n")
    return rules + "\n" + OUTPUT_REMINDER + "\n\n" + json.dumps(payload, ensure_ascii=False)

def parse_json_array(content):
    """Trích JSON array từ content model (bỏ ```json fences / text thừa)."""
    c = content.strip()
    if c.startswith('```'):
        c = c.split('\n', 1)[1] if '\n' in c else c
        c = c.rsplit('```', 1)[0]
    c = c.strip()
    i, j = c.find('['), c.rfind(']')
    if i != -1 and j != -1 and j > i: c = c[i:j + 1]
    return json.loads(c)

def load_keys_from(path, dead=None):
    out = []
    for ln in read_text(path).split('\n'):
        ln = ln.strip()
        if ln and not ln.startswith('#') and ln not in out: out.append(ln)
    return [k for k in out if not dead or k not in dead]

def sample_for_prompt(pairs, max_lines=120, max_chars=6000):
    """Lấy mẫu rải đều (đầu/giữa/cuối) từ các dòng cần dịch để gửi cho AI sinh prompt."""
    cand = [(k, v) for k, v in pairs if v.strip() and v != k]
    if not cand: return ''
    if len(cand) > max_lines:
        step = len(cand) / max_lines
        cand = [cand[int(i * step)] for i in range(max_lines)]
    out, ch = [], 0
    for k, v in cand:
        ln = '%s=%s' % (k, v)
        if ch + len(ln) > max_chars: break
        out.append(ln); ch += len(ln)
    return '\n'.join(out)

def estimate_tokens(text):
    """Ước lượng số token (≈ ký tự/4, tối thiểu = số từ) — KHÔNG cần tokenizer ngoài.
    Chỉ để HIỂN THỊ/cảnh báo; con số API tính thật có thể lệch."""
    if not text: return 0
    return max(len(text) // 4, len(text.split()))

def sample_stats(text):
    """Thống kê file mẫu cho tab System Prompt (hàm THUẦN -> chạy ở thread nền).
    Trả {lines, chars, tokens, sample_tokens}: tokens = ước lượng CẢ file;
    sample_tokens = ước lượng phần MẪU thực sự gửi cho AI khi sinh prompt (sample_for_prompt)."""
    if not text: return {'lines': 0, 'chars': 0, 'tokens': 0, 'sample_tokens': 0}
    pairs = parse_doc(text).pairs
    translatable = sum(1 for k, v in pairs if v.strip() and v != k)
    return {'lines': translatable, 'chars': len(text), 'tokens': estimate_tokens(text),
            'sample_tokens': estimate_tokens(sample_for_prompt(pairs))}

# ============================== PROVIDER (2 format API) ==============================
class RateLimit(Exception): pass
class DeadKey(Exception): pass
class Transient(Exception): pass

def _norm_base(base):
    """Chuẩn hóa base_url: bỏ '/' thừa và NÂNG http->https cho host công khai.
    (Server LLM ép https; gọi http -> 301 và httpx đổi POST thành GET -> hỏng.
     Giữ http cho localhost / LAN nội bộ để vẫn dùng được server dev.)"""
    base = (base or '').strip().rstrip('/')
    if base.startswith('http://'):
        host = base[len('http://'):].split('/')[0].split(':')[0].lower()
        local = (host in ('localhost', '127.0.0.1', '0.0.0.0', '::1')
                 or host.startswith('127.') or host.startswith('192.168.') or host.startswith('10.'))
        if not local:
            base = 'https://' + base[len('http://'):]
    return base

def _join_v1(base, suffix):
    """Ghép endpoint, tự bổ sung /v1. Người dùng chỉ cần điền domain (vd http://chat.trollllm.xyz);
    chấp nhận dư dấu '/' hoặc đã sẵn '/v1'. -> luôn ra <base>/v1<suffix>."""
    base = _norm_base(base)
    if base.endswith('/v1'):
        base = base[:-3].rstrip('/') + '/v1'   # gộp '/v1' (kể cả khi có '//v1')
    else:
        base = base + '/v1'
    return base + suffix

class Provider:
    """Base: giữ httpx client (pooling) + retry/map-lỗi CHUNG. Subclass override 4 hàm THUẦN."""
    name = 'base'
    def __init__(self, base_url, max_tokens=8192, temperature=0.3, timeout=180, max_conns=32, debug=False, anthropic_beta=''):
        self.base_url = _norm_base(base_url)
        self.max_tokens = max_tokens; self.temperature = temperature; self.timeout = timeout
        self.debug = debug                      # True -> in chi tiết lỗi API ra console (stderr)
        self.anthropic_beta = (anthropic_beta or '').strip()   # chuỗi 'anthropic-beta' (vd context-1m-2025-08-07); rỗng = không gửi
        self.last_truncated = False             # phản hồi gần nhất có bị CẮT do chạm trần output?
        self._limits = httpx.Limits(max_connections=max_conns, max_keepalive_connections=max_conns)
        self._client = None; self._client_lock = threading.Lock()

    def _with_beta(self, headers):
        """Gắn header 'anthropic-beta' (vd context-1m-2025-08-07 để mở context 1M) nếu được bật.
        Router OpenAI-compatible proxy Claude thường chuyển tiếp header này; model mới đã 1M sẵn nên vô hại."""
        if self.anthropic_beta:
            headers['anthropic-beta'] = self.anthropic_beta
        return headers

    def _rtext(self, r):
        try: return (r.text or '')[:DEBUG_MAX]
        except Exception: return ''

    def _max_tokens_cap_from_error(self, text):
        """Nếu lỗi 400 là 'max_tokens vượt trần OUTPUT của model' (vd 'max_tokens: 1000000 > 128000,
        which is the maximum allowed number of output tokens'), trả về TRẦN đó để tự giảm rồi thử lại.
        CHỈ áp cho lỗi liên quan max_tokens/output token (KHÔNG đụng lỗi context-length đầu vào)."""
        low = (text or '').lower()
        if 'max_tokens' not in low and 'output token' not in low: return None
        cap = parse_max_tokens_cap(text)
        return cap if (cap and cap < self.max_tokens) else None

    def _context_overflow_cap_from_error(self, text):
        """Nếu lỗi 400 là 'VƯỢT CONTEXT WINDOW' (tổng input+output > cửa sổ ngữ cảnh model/router,
        vd 9Router giới hạn 128000), trả max_tokens MỚI = nửa cửa sổ (chừa nửa kia cho input) hoặc None.
        KHÁC lỗi 'max_tokens > trần OUTPUT': ở đây max_tokens đang chiếm gần hết cửa sổ -> giảm để có chỗ cho input.
        CHỈ giảm khi giá trị mới NHỎ HƠN max_tokens hiện tại (max_tokens đã nhỏ mà vẫn vượt -> do INPUT quá to)."""
        if not _CONTEXT_ERR_RE.search(text or ''): return None
        limit = parse_max_tokens_cap(text)
        if not limit: return None
        new_max = max(1024, limit // 2)
        return new_max if new_max < self.max_tokens else None

    def _debug_dump(self, url, body, detail):
        """In chi tiết lỗi API ra stderr (console). KHÔNG BAO GIỜ in header/API key (chỉ in
        URL, model trong body, và nội dung API TRẢ VỀ). Chỉ chạy khi self.debug=True."""
        if not self.debug: return
        try:
            model = body.get('model') if isinstance(body, dict) else ''
            sys.stderr.write('\n[API-DEBUG %s] %s%s\n  %s\n'
                             % (time.strftime('%H:%M:%S'), url,
                                (' [model=%s]' % model) if model else '', detail))
            sys.stderr.flush()
        except Exception:
            pass

    # --- subclass override (PURE) ---
    def endpoint(self): raise NotImplementedError
    def headers(self, key): raise NotImplementedError
    def build_body(self, model, system, user): raise NotImplementedError
    def parse_content(self, j): raise NotImplementedError
    def is_truncated(self, j): return False    # phản hồi có bị cắt do chạm trần output không?
    def list_models_endpoint(self): return None
    def parse_models(self, j): return []

    # --- httpx client dùng chung (lazy, thread-safe; tái dùng TLS connection) ---
    @property
    def client(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    kw = dict(limits=self._limits, timeout=httpx.Timeout(self.timeout),
                              follow_redirects=True)   # tự theo 301 (vd http -> https) cho GET
                    try:
                        self._client = httpx.Client(http2=True, **kw)
                    except Exception:   # thiếu gói h2 -> dùng HTTP/1.1 keep-alive (vẫn pooling)
                        self._client = httpx.Client(**kw)
        return self._client

    def close(self):
        c = self._client; self._client = None
        if c is not None:
            try: c.close()
            except Exception: pass

    # --- CHUNG: map lỗi theo status code ---
    def _raise_for_status(self, r):
        code = r.status_code
        if code < 400: return
        try: msg = r.text
        except Exception: msg = ''
        low = msg.lower()
        if code == 429 or 'rate' in low or 'quota' in low or 'resource_exhausted' in low:
            raise RateLimit(msg)
        if code in (401, 403):
            raise DeadKey(msg)
        if code in (500, 502, 503, 504, 408):
            raise Transient('HTTP %d' % code)
        raise Transient('HTTP %d: %s' % (code, msg[:120]))

    def _post(self, url, headers, body, timeout=None):
        try:
            r = self.client.post(url, headers={**headers, 'Content-Type': 'application/json'},
                                 json=body, timeout=timeout or self.timeout)
        except httpx.HTTPError as e:
            self._debug_dump(url, body, 'NETWORK ERROR: %s' % str(e)[:DEBUG_MAX])
            raise Transient(str(e)[:120])
        if r.status_code >= 400:
            detail = self._rtext(r)
            self._debug_dump(url, body, 'HTTP %d | response: %s' % (r.status_code, detail))
            if r.status_code == 400:
                cap = self._max_tokens_cap_from_error(detail)
                if cap:                       # max_tokens vượt trần OUTPUT của model -> tự GIẢM rồi báo retry
                    old = self.max_tokens; self.max_tokens = cap
                    raise Transient('max_tokens %d vượt trần model (%d) -> đã giảm còn %d rồi thử lại'
                                    % (old, cap, cap))
                cap2 = self._context_overflow_cap_from_error(detail)
                if cap2:                      # input + max_tokens vượt CONTEXT WINDOW -> giảm max_tokens chừa chỗ cho input
                    old = self.max_tokens; self.max_tokens = cap2
                    raise Transient('Vượt context window (cửa sổ ngữ cảnh) -> đã giảm max_tokens %d xuống %d rồi thử lại'
                                    % (old, cap2))
        self._raise_for_status(r)
        try:
            return r.json()
        except Exception:
            self._debug_dump(url, body, 'HTTP %d no_json | response: %s' % (r.status_code, self._rtext(r)))
            raise Transient('no_json: ' + (self._rtext(r)[:120]))

    def call(self, model, key, system, user):
        url = self.endpoint(); body = self.build_body(model, system, user)
        j = self._post(url, self.headers(key), body)
        try:
            content = self.parse_content(j)
        except Exception as e:      # 200 + JSON nhưng thiếu content / sai cấu trúc -> in cả JSON
            self._debug_dump(url, body, 'parse lỗi: %s | json: %s'
                             % (str(e)[:200], json.dumps(j, ensure_ascii=False)[:DEBUG_MAX]))
            raise
        self.last_truncated = self.is_truncated(j)   # bị cắt do chạm trần output?
        if self.last_truncated:
            self._debug_dump(url, body, 'CẢNH BÁO: phản hồi bị CẮT do chạm trần output (max_tokens=%s). '
                             'Tăng max_tokens nếu cần nội dung dài hơn.' % self.max_tokens)
        return content

    def list_models(self, key):
        url = self.list_models_endpoint()
        if not url: return []
        try:
            r = self.client.get(url, headers=self.headers(key), timeout=20)
            if r.status_code >= 400: return []
            return self.parse_models(r.json())
        except Exception:
            return []

class OpenAIProvider(Provider):
    name = 'openai'
    def endpoint(self): return _join_v1(self.base_url, '/chat/completions')
    def headers(self, key): return self._with_beta({'Authorization': 'Bearer ' + key})
    def build_body(self, model, system, user):
        body = {'model': model,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}],
                'max_tokens': self.max_tokens,
                'stream': False}   # ÉP non-stream: nhiều router (vd 9Router) MẶC ĐỊNH trả SSE -> r.json() hỏng
        if self.temperature is not None:   # model gpt-5/codex/o-series từ chối 'temperature' -> cho phép bỏ
            body['temperature'] = self.temperature
        return body
    def parse_content(self, j):
        try: return j['choices'][0]['message']['content']
        except Exception: raise Transient('no_content: ' + json.dumps(j)[:150])
    def is_truncated(self, j):
        try: return j['choices'][0].get('finish_reason') == 'length'
        except Exception: return False
    def list_models_endpoint(self): return _join_v1(self.base_url, '/models')
    def parse_models(self, j):
        return sorted(m['id'] for m in j.get('data', []) if m.get('id'))

class AnthropicProvider(Provider):
    name = 'anthropic'
    def endpoint(self): return _join_v1(self.base_url, '/messages')
    def headers(self, key):
        return self._with_beta({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    def build_body(self, model, system, user):
        body = {'model': model, 'max_tokens': self.max_tokens, 'system': system,
                'messages': [{'role': 'user', 'content': user}]}
        if self.temperature is not None:
            body['temperature'] = self.temperature
        return body
    def parse_content(self, j):
        try:
            blocks = j['content']
            txt = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            return txt or blocks[0]['text']
        except Exception:
            raise Transient('no_content: ' + json.dumps(j)[:150])
    def is_truncated(self, j):
        return j.get('stop_reason') == 'max_tokens'
    def list_models_endpoint(self): return None

def build_anthropic_beta(cfg):
    """Dựng chuỗi header 'anthropic-beta' (nối bằng ',') từ config. Hiện chỉ có cờ context_1m
    (mở context window 1M cho Claude). Tách riêng để test + dễ thêm cờ beta khác sau này."""
    betas = []
    if cfg.get('context_1m'):
        betas.append(CONTEXT_1M_BETA)
    extra = (cfg.get('anthropic_beta') or '').strip()   # cho phép tự nhập thêm beta thô (tùy chọn)
    if extra:
        betas.extend(b.strip() for b in re.split(r'[,\s]+', extra) if b.strip())
    return ','.join(dict.fromkeys(betas))               # bỏ trùng, giữ thứ tự

def make_provider(cfg):
    cls = {'openai': OpenAIProvider, 'anthropic': AnthropicProvider}.get(cfg.get('provider', 'openai'), OpenAIProvider)
    max_conns = max(8, int(cfg.get('workers', 8)) + 4)   # pool đủ cho số luồng song song
    # send_temperature=False -> KHÔNG gửi 'temperature' (model gpt-5/codex/o-series từ chối tham số này)
    temp = cfg.get('temperature', 0.3) if cfg.get('send_temperature', True) else None
    return cls(cfg.get('base_url', ''), cfg.get('max_tokens', 8192),
               temp, cfg.get('timeout', 180), max_conns, cfg.get('debug', False),
               build_anthropic_beta(cfg))

# ============================== TIỆN ÍCH CẤP CAO ==============================
# (provider tạm dùng 1 lần -> đóng client httpx sau khi xong)
def list_models(provider, key):
    try: return provider.list_models(key)
    finally: provider.close()

_TOKEN_LIMIT_RE = re.compile(
    r'context[_ ]length|maximum context|context window|too many tokens'
    r'|tokens? (?:limit|exceed)|max_tokens|reduce the length|string too long', re.I)
def is_token_limit_error(msg):
    """Nhận diện lỗi GIỚI HẠN TOKEN/độ dài (vd max_tokens quá lớn, vượt context length)."""
    return bool(_TOKEN_LIMIT_RE.search(msg or ''))

# Trích TRẦN max_tokens model cho phép từ thông báo lỗi 400 (nhiều dạng router/Anthropic/OpenAI):
#   Anthropic: "max_tokens: 1000000 > 128000, which is the maximum allowed number of output tokens"
#   OpenAI:    "max_tokens is too large: ... supports at most 16384 ..." / "maximum ... is 4096"
_MAXTOK_CAP_RE = [
    re.compile(r'>\s*(\d{3,})'),                                  # 'X > 128000' (Anthropic)
    re.compile(r'at most\s+(\d{3,})', re.I),                      # 'supports at most 16384'
    re.compile(r'(?:max(?:imum)?|context|window|limit)[^\d]{0,40}?(\d{3,})', re.I),  # 'maximum/context/window/limit ... 128000'
]
# Lỗi VƯỢT CONTEXT WINDOW (tổng input+output > cửa sổ ngữ cảnh, vd 9Router 128000) — KHÁC lỗi 'max_tokens > trần OUTPUT'
_CONTEXT_ERR_RE = re.compile(
    r'context[ _-]?(?:length|window|limit)|maximum context|context_length_exceeded'
    r'|reduce the length of (?:the )?messages', re.I)
def parse_max_tokens_cap(msg):
    """Trả về số TRẦN max_tokens model cho phép (int) đọc được từ thông báo lỗi, hoặc None.
    Dùng để TỰ GIẢM max_tokens khi người dùng đặt cao hơn trần output của model rồi thử lại."""
    if not msg: return None
    for rx in _MAXTOK_CAP_RE:
        m = rx.search(msg)
        if m:
            try: return int(m.group(1))
            except (ValueError, IndexError): pass
    return None

def test_connection(provider, key, model):
    """Gửi 1 request nhỏ. Trả (ok: bool, msg: str).
    Nếu max_tokens vượt trần output của model -> provider TỰ GIẢM, hàm thử lại 1 lần rồi báo đã giảm."""
    try:
        before = provider.max_tokens
        try:
            txt = provider.call(model, key, 'You are a test.', 'Reply with exactly: OK')
        except Transient as e:
            if 'đã giảm' in str(e):     # provider vừa tự giảm max_tokens (vượt trần model) -> thử lại 1 lần
                txt = provider.call(model, key, 'You are a test.', 'Reply with exactly: OK')
            else:
                raise
        msg = (txt or '').strip()[:80] or 'OK'
        if provider.max_tokens != before:
            msg += '  (đã tự giảm max_tokens xuống %d cho model này)' % provider.max_tokens
        return True, msg
    except RateLimit as e:
        return False, 'Hết quota / rate-limit: %s' % str(e)[:100]
    except DeadKey as e:
        return False, 'API key không hợp lệ (401/403): %s' % str(e)[:100]
    except Transient as e:
        s = str(e)
        if 'temperature' in s.lower() and ('support' in s.lower() or 'unsupported' in s.lower()):
            return False, "Model KHÔNG nhận tham số 'temperature'. Hãy BỎ TÍCH ô 'temperature' ở tab API rồi thử lại."
        if is_token_limit_error(s):
            return False, "Vượt GIỚI HẠN TOKEN (vd max_tokens quá lớn / vượt context). Hãy GIẢM 'max_tokens' ở tab API rồi thử lại."
        return False, 'Lỗi tạm thời (sẽ retry khi dịch): %s' % s[:100]
    except Exception as e:
        return False, str(e)[:120]
    finally:
        provider.close()

def gen_system_prompt(provider, key, model, sample_text, game_name='', tone='', note='', timeout=180, gen_max_tokens=16384):
    """TỰ SINH system prompt dịch từ tên game + mẫu text game EN.
    Trần output = gen_max_tokens (16384): ĐỦ RỘNG cho prompt giàu (glossary game lớn, vd FF7
    Rebirth ~6k token) để KHÔNG bị cắt ngang, nhưng vẫn chặn trường hợp người dùng đặt max_tokens
    rất cao để DỊCH (tới 1.000.000) khiến API từ chối 'max_tokens quá lớn'. 16384 = trần output
    của GPT-4o và an toàn với Claude (tới 64k). Chỉ HẠ xuống khi max_tokens hiện tại lớn hơn;
    nếu người dùng đã đặt nhỏ hơn (model output bé) thì giữ nguyên. Khôi phục max_tokens cũ sau khi xong.
    Sau khi gọi, provider.last_truncated cho biết prompt có bị cắt (chạm trần) hay không."""
    provider.timeout = timeout
    prev_mt = provider.max_tokens
    if not prev_mt or prev_mt > gen_max_tokens:
        provider.max_tokens = gen_max_tokens
    try:
        user = GEN_META_USER
        if game_name: user += '\nTÊN GAME: %s\n' % game_name
        if tone: user += 'TONE MONG MUỐN: %s\n' % tone
        if note: user += 'GHI CHÚ THÊM: %s\n' % note
        user += '\n===== MẪU TEXT GAME (EN) =====\n' + sample_text
        return provider.call(model, key, GEN_META_SYS, user).strip()
    finally:
        provider.max_tokens = prev_mt
        provider.close()

def build_system_prompt(cfg):
    """Ghép system prompt khi dịch: ưu tiên sysprompt (tự sinh/sửa tay), nếu rỗng -> luật mặc định."""
    sp = (cfg.get('sysprompt') or '').strip()
    if sp:
        parts = [sp]
    else:
        parts = [UNIVERSAL_RULES]
        if cfg.get('tone'): parts.append('=== VĂN PHONG / TONE ===\n' + cfg['tone'])
        if cfg.get('context'): parts.append('=== BỐI CẢNH & CỐT TRUYỆN ===\n' + cfg['context'])
        rules = read_text(cfg.get('prompt', '')).strip()
        if rules: parts.append('=== LUẬT DỊCH RIÊNG ===\n' + rules)
        gloss = read_text(cfg.get('glossary', '')).strip() if cfg.get('glossary') else ''
        if gloss: parts.append('=== GLOSSARY ===\n' + gloss)
    parts.append(OUTPUT_REMINDER)
    return '\n\n'.join(parts)

# ============================== CHECKPOINT / RESUME ==============================
def load_progress(pairs, eng_of, out_path):
    """Đọc mốc đã dịch từ file output + <out>.done.txt -> (vals, done).
    File OUTPUT là nguồn chân lý: chỉ coi 1 key là 'đã xong' khi output thật sự có dòng đó
    -> nếu xóa output mà còn done.txt thì vẫn dịch lại đúng (không bỏ sót)."""
    out_path = out_path or ''
    vals = {}
    if out_path and os.path.exists(out_path):
        vals = dict(parse_doc(read_text(out_path)).pairs)   # nguồn chân lý = output (đa-format)
    raw_done = set(x.strip() for x in read_text(out_path + '.done.txt').split('\n') if x.strip())
    done = {k for k in raw_done if k in vals}
    for k, v in vals.items():                      # tự dò dòng đã dịch sẵn trong output
        if k in eng_of and v.strip() and v != eng_of[k]: done.add(k)
    return vals, done

def resume_status(src, out):
    """Tiến độ đã lưu để UI hiển thị (KHÔNG sửa file). Trả {total, done, todo}
    tính theo SỐ DÒNG CẦN DỊCH (bỏ dòng rỗng / ID=ID)."""
    txt = read_text(src)
    if not txt: return {'total': 0, 'done': 0, 'todo': 0}
    pairs = parse_doc(txt).pairs
    eng_of = {k: v for k, v in pairs}
    _, done = load_progress(pairs, eng_of, out)
    translatable = [k for k, v in pairs if v.strip() and v != k]
    d = sum(1 for k in translatable if k in done)
    return {'total': len(translatable), 'done': d, 'todo': len(translatable) - d}

# status: 0 = ok/không cần dịch, 1 = chưa dịch, 2 = nghi lỗi placeholder/vượt byte
def build_preview_rows(src, out, byte_limit=False):
    """Đối chiếu key/EN/VI + SO SÁNH BYTE cho tab XEM TRƯỚC (hàm THUẦN, chạy được ở thread nền).
    Trả (rows, stats): rows = list (key, en, vi, status, en_bytes, vi_bytes); stats theo dòng cần dịch.
    Cột byte LUÔN được tính (để xem đối chiếu). byte_limit=True -> dòng có vi_bytes > en_bytes bị xếp
    'nghi lỗi' (status 2). 'over' = số dòng đã dịch mà bản dịch VƯỢT byte gốc (luôn đếm, để cảnh báo)."""
    txt = read_text(src)
    if not txt:
        return [], {'total': 0, 'done': 0, 'pending': 0, 'bad': 0, 'over': 0}
    pairs = parse_doc(txt).pairs
    vmap = {}
    if out and os.path.exists(out):
        vmap = dict(parse_doc(read_text(out)).pairs)
    rows = []; done = pending = bad = over = 0
    for k, en in pairs:
        vi = vmap.get(k, '')
        en_b = utf8_len(en); vi_b = utf8_len(vi)
        if not en.strip() or en == k:
            status = 0
        elif not vi.strip() or vi == en:
            status = 1
        elif check_line(en, vi, byte_limit):
            status = 2
        else:
            status = 0
        rows.append((k, en, vi, status, en_b, vi_b))
        if en.strip() and en != k:
            done += status == 0; pending += status == 1; bad += status == 2
            if vi.strip() and vi != en and vi_b > en_b: over += 1
    return rows, {'total': done + pending + bad, 'done': done, 'pending': pending, 'bad': bad, 'over': over}

# ============================== DỊCH CẢ THƯ MỤC (helper thuần) ==============================
# Dịch mọi file khớp đuôi trong 1 thư mục -> thư mục song song '<tên>_vi' (giữ cây thư mục).
# Mỗi file dùng lại TranslationRun + resume per-file (output từng file là nguồn chân lý).
_SKIP_SUFFIX = ('.done.txt', '.tmp')   # artifact do tool sinh ra -> KHÔNG coi là file nguồn

def norm_exts(exts):
    """Chuẩn hóa đuôi file -> set('.txt','.json',...) chữ thường. Rỗng/None -> None (mọi file).
    Nhận chuỗi ('.txt .json' / 'txt,json' / '*.txt') hoặc list/set; tự thêm '.', bỏ '*'."""
    if exts is None: return None
    parts = re.split(r'[,\s]+', exts.strip()) if isinstance(exts, str) else list(exts)
    out = set()
    for p in parts:
        p = str(p).strip().lstrip('*').lower()
        if not p: continue
        if not p.startswith('.'): p = '.' + p
        out.add(p)
    return out or None

def list_folder_files(folder, exts=None):
    """Liệt kê file trong folder (ĐỆ QUY) khớp đuôi 'exts' -> list đường dẫn TƯƠNG ĐỐI (đã sort).
    Bỏ file/thư mục ẩn và artifact (.done.txt/.tmp). KHÔNG đọc nội dung (chỉ duyệt tên -> nhanh)."""
    if not folder or not os.path.isdir(folder): return []
    exts = norm_exts(exts)
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))   # bỏ thư mục ẩn + duyệt ổn định
        for fn in sorted(files):
            if fn.startswith('.'): continue
            low = fn.lower()
            if any(low.endswith(s) for s in _SKIP_SUFFIX): continue
            if exts is not None and os.path.splitext(low)[1] not in exts: continue
            out.append(os.path.relpath(os.path.join(root, fn), folder))
    return out

def default_out_folder(src_folder):
    """Gợi ý thư mục kết quả song song: '/a/b/text_en' -> '/a/b/text_en_vi'."""
    s = (src_folder or '').rstrip('/\\')
    return (s + '_vi') if s else ''

def folder_overview(folder, out_folder, exts=None):
    """Đếm NHANH cho UI (KHÔNG đọc nội dung): {files, have_out}.
    files = số file khớp đuôi; have_out = số file đã có kết quả tương ứng ở thư mục đích."""
    files = list_folder_files(folder, exts)
    have = 0
    if out_folder:
        for rel in files:
            if os.path.isfile(os.path.join(out_folder, rel)): have += 1
    return {'files': len(files), 'have_out': have}

# ============================== ORCHESTRATOR ĐA LUỒNG ==============================
class TranslationRun:
    """Điều phối dịch đa luồng. Phát sự kiện qua emit(evt: dict). stop = threading.Event.
    provider: truyền sẵn để DÙNG CHUNG (vd dịch cả thư mục) -> tái dùng pool httpx; None -> tự tạo."""
    def __init__(self, cfg, emit, stop, provider=None):
        self.cfg = cfg; self.emit = emit; self.stop = stop
        self.provider = provider if provider is not None else make_provider(cfg)
        self.sys_p = build_system_prompt(cfg)
        self.models = cfg.get('models') or [cfg.get('model', '')]
        self.models = [m for m in self.models if m]
        self.lock = threading.Lock()
        self.combo_ok = {}; self.dead = set(); self.rr = 0
        self.slot_map = {}; self.slot_next = 0
        self.stats = {'by_model': {}, 'ok': 0, 'err': 0, 'retries': 0}
        self.t0 = time.time(); self.done0 = 0
        self.total = 0; self.ndone = 0

    # ---- emit helpers ----
    def log(self, s): self.emit({'type': 'log', 'msg': s})

    def emit_progress(self):
        el = max(1e-6, time.time() - self.t0)
        rate = (self.ndone - self.done0) / el          # dòng/giây
        rem = (self.total - self.ndone) / rate if rate > 0 else 0
        pct = int(self.ndone * 100 / self.total) if self.total else 0
        self.emit({'type': 'progress', 'done': self.ndone, 'total': self.total, 'pct': pct,
                   'rate': rate, 'eta_sec': int(rem), 'elapsed': int(el)})

    def emit_stats(self):
        self.emit({'type': 'stats', **{k: (dict(v) if isinstance(v, dict) else v)
                                        for k, v in self.stats.items()}})

    def slot_of(self):
        tid = threading.get_ident()
        with self.lock:
            if tid not in self.slot_map:
                self.slot_map[tid] = self.slot_next; self.slot_next += 1
            return self.slot_map[tid]

    # ---- key/model rotation ----
    def _live_keys(self):
        src = self.cfg.get('keys') or []
        if isinstance(src, str):
            src = load_keys_from(src)
        return [k for k in src if k not in self.dead]

    def pick_combo(self):
        with self.lock:
            keys = self._live_keys()
            if not keys: return ('__NOKEY__', None)
            combos = [(m, k) for m in self.models for k in keys]
            now = time.time()
            ready = [c for c in combos if self.combo_ok.get(c, 0) <= now]
            if not ready:
                return ('__WAIT__', max(1, min(self.combo_ok[c] for c in combos) - now))
            c = ready[self.rr % len(ready)]; self.rr += 1
            return c

    def translate_batch(self, items, label, batch_id, slot):
        """Dịch 1 lô -> dict {id: vi}. Tự retry + xoay model/key."""
        user_text = build_user_prompt(items)
        retry = 0
        while not self.stop.is_set():
            mdl, key = self.pick_combo()
            if mdl == '__NOKEY__':
                self.log('   !! Chưa có API key — thêm key rồi chờ 15s'); time.sleep(15); continue
            if mdl == '__WAIT__':
                self.emit({'type': 'worker', 'slot': slot, 'batch_id': batch_id,
                           'model': '', 'status': 'waiting'})
                time.sleep(min(key, 8)); continue
            self.emit({'type': 'worker', 'slot': slot, 'batch_id': batch_id,
                       'model': mdl, 'status': 'translating'})
            try:
                content = self.provider.call(mdl, key, self.sys_p, user_text)
                results = parse_json_array(content)
                out = {}
                for r in results:
                    if isinstance(r, dict) and 'id' in r and 'vi' in r:
                        out[r['id']] = str(r['vi'])
                miss = [it['id'] for it in items if it['id'] not in out]
                if len(miss) > len(items) * 0.25 and retry < self.cfg.get('retries', 5):
                    retry += 1
                    with self.lock: self.stats['retries'] += 1
                    self.log('   [%s] thiếu %d mục -> thử lại' % (label, len(miss))); continue
                with self.lock:
                    self.stats['ok'] += 1
                    self.stats['by_model'][mdl] = self.stats['by_model'].get(mdl, 0) + 1
                return out
            except RateLimit:
                with self.lock: self.combo_ok[(mdl, key)] = time.time() + 60
                self.emit({'type': 'batch', 'batch_id': batch_id, 'state': 'retry',
                           'model': mdl, 'err': 'rate-limit', 'label': label})
                self.log('   [%s] %s hết quota -> đổi model/key' % (label, mdl)); continue
            except DeadKey:
                with self.lock: self.dead.add(key)
                self.log('   [%s] key %s.. không hợp lệ -> bỏ' % (label, str(key)[:12])); continue
            except (Transient, json.JSONDecodeError, ValueError) as e:
                with self.lock:
                    self.combo_ok[(mdl, key)] = time.time() + 8
                    self.stats['retries'] += 1
                retry += 1
                self.emit({'type': 'batch', 'batch_id': batch_id, 'state': 'retry',
                           'model': mdl, 'err': str(e)[:60], 'label': label})
                self.log('   [%s] lỗi %s (thử %d) -> đổi/đợi' % (label, str(e)[:60], retry))
                if retry > self.cfg.get('retries', 5) + 4:
                    with self.lock: self.stats['err'] += 1
                    return {}
                time.sleep(min(2 * retry, 10)); continue
        return {}

    def run(self):
        cfg = self.cfg
        src_txt = read_text(cfg['src'])
        if not src_txt:
            self.emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0,
                       'msg': 'Không đọc được file đầu vào.'}); return
        doc = parse_doc(src_txt)                  # tự nhận diện KEY=VALUE hoặc Resident $KEY-block
        pairs = doc.pairs
        eng_of = {k: v for k, v in pairs}
        out_path = cfg['out']; donef_path = out_path + '.done.txt'
        vals, done = load_progress(pairs, eng_of, out_path)   # mốc đã dịch (resume)
        todo = [(k, v) for k, v in pairs if k not in done and v.strip() and v != k]
        self.total = len(pairs); self.ndone = len(done); self.done0 = len(done)
        self.emit_progress()
        if done:
            self.log('Resume: đã có %d dòng dịch trước đó -> chỉ dịch %d dòng còn lại.' % (len(done), len(todo)))
        self.log('=== BẮT ĐẦU === tổng %d | đã xong %d | còn %d | %d luồng | model: %s'
                 % (self.total, len(done), len(todo), cfg.get('workers', 8), ', '.join(self.models)))
        donef = open(donef_path, 'a', encoding='utf-8')

        byte_limit = cfg.get('byte_limit', False)   # ép byte bản dịch <= byte gốc EN (gửi max_bytes cho AI)

        def run_parallel(work_pairs, label):
            id_to_key = {}; items = []
            for i, (k, en) in enumerate(work_pairs):
                id_to_key[i] = k
                it = {'id': i, 'en': en, 'placeholders': extract_placeholders(en)}
                if byte_limit: it['max_bytes'] = utf8_len(en)
                items.append(it)
            batches = make_batches(items, cfg.get('maxlines', 50), cfg.get('maxchars', 8000))
            self.emit({'type': 'batch_init', 'n_batches': len(batches), 'label': label})
            self.log('  %s: %d dòng -> %d lô (chạy %d luồng)'
                     % (label, len(items), len(batches), cfg.get('workers', 8)))

            def handle(args):
                bi, batch = args
                if self.stop.is_set(): return
                slot = self.slot_of()
                self.emit({'type': 'batch', 'batch_id': bi, 'state': 'running',
                           'n_lines': len(batch), 'label': label})
                got = self.translate_batch(batch, '%s %d/%d' % (label, bi + 1, len(batches)), bi, slot)
                if self.stop.is_set(): return
                with self.lock:
                    for it in batch:
                        k = id_to_key[it['id']]
                        vi = got.get(it['id'])
                        vals[k] = vi if (vi and vi.strip()) else eng_of[k]
                        if k not in done: done.add(k); donef.write(k + '\n')
                    donef.flush(); write_doc(out_path, doc, vals)
                    self.ndone = len(done)
                self.emit({'type': 'batch', 'batch_id': bi,
                           'state': 'done' if got else 'error', 'label': label})
                self.emit({'type': 'worker', 'slot': slot, 'batch_id': None,
                           'model': '', 'status': 'idle'})
                self.emit_progress(); self.emit_stats()

            with ThreadPoolExecutor(max_workers=cfg.get('workers', 8)) as ex:
                list(ex.map(handle, list(enumerate(batches))))
            return not self.stop.is_set()

        if todo and not run_parallel(todo, 'Dịch'):
            donef.close()
            self.emit({'type': 'finished', 'status': 'stopped', 'total': self.total,
                       'done': len(done), 'bad': 0, 'msg': 'Đã dừng (resume sau).'}); return

        for rnd in range(1, cfg.get('rounds', 6) + 1):
            if self.stop.is_set(): break
            bad = [k for k, _ in pairs if k in vals and eng_of[k].strip()
                   and eng_of[k] != k and check_line(eng_of[k], vals[k], byte_limit)]
            if not bad:
                donef.close()
                self.emit({'type': 'finished', 'status': 'ok', 'total': self.total,
                           'done': self.total, 'bad': 0,
                           'msg': 'HOÀN TẤT - SẠCH LỖI! (%d dòng)' % self.total})
                return
            self.log('--- Vòng kiểm %d: %d dòng lỗi -> dịch lại ---' % (rnd, len(bad)))
            with self.lock:
                for k in bad: done.discard(k)
            self.ndone = len(done)
            if not run_parallel([(k, eng_of[k]) for k in bad], 'Sửa-v%d' % rnd):
                donef.close()
                self.emit({'type': 'finished', 'status': 'stopped', 'total': self.total,
                           'done': len(done), 'bad': len(bad), 'msg': 'Đã dừng (resume sau).'}); return
        donef.close()
        bad = [k for k, _ in pairs if k in vals and eng_of[k].strip()
               and eng_of[k] != k and check_line(eng_of[k], vals[k], byte_limit)]
        self.emit({'type': 'finished', 'status': 'ok', 'total': self.total, 'done': len(done),
                   'bad': len(bad), 'msg': 'Xong (còn %d dòng nghi lỗi - bấm Bắt đầu lại để sửa).' % len(bad)})

def run_translation(cfg, emit, stop):
    """Điểm vào engine. Chạy blocking (gọi bên trong QThread ở app.py)."""
    run = None
    try:
        run = TranslationRun(cfg, emit, stop)
        run.run()
    except Exception as e:
        import traceback
        emit({'type': 'log', 'msg': '!! LỖI: %s\n%s' % (e, traceback.format_exc()[:600])})
        emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0, 'msg': str(e)[:120]})
    finally:
        if run is not None:
            try: run.provider.close()      # đóng connection pool httpx
            except Exception: pass

def run_folder_translation(cfg, emit, stop):
    """Điểm vào engine cho chế độ THƯ MỤC. Dịch mọi file khớp đuôi trong cfg['src'] (thư mục)
    -> cfg['out'] (thư mục song song), GIỮ NGUYÊN cây thư mục. Mỗi file = 1 TranslationRun
    (resume per-file). Dùng CHUNG 1 provider cho mọi file (tái dùng pool httpx).
    Sự kiện thêm: folder_init {n_files,exts}, folder_file {index,total,name,state,...}.
    finished CỦA TỪNG FILE được nuốt lại -> chỉ phát MỘT finished tổng kết ở cuối."""
    folder = cfg.get('src', ''); out_folder = cfg.get('out', '')
    exts = norm_exts(cfg.get('exts'))
    if not folder or not os.path.isdir(folder):
        emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0,
              'msg': 'Thư mục nguồn không hợp lệ.'}); return
    if not out_folder:
        emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0,
              'msg': 'Chưa chọn thư mục kết quả.'}); return
    files = list_folder_files(folder, exts)
    emit({'type': 'folder_init', 'n_files': len(files), 'exts': sorted(exts) if exts else []})
    if not files:
        emit({'type': 'finished', 'status': 'error', 'total': 0, 'done': 0, 'bad': 0,
              'msg': 'Không tìm thấy file nào khớp đuôi đã chọn trong thư mục.'}); return
    emit({'type': 'log', 'msg': '=== DỊCH THƯ MỤC === %d file | đuôi: %s -> %s'
          % (len(files), (' '.join(sorted(exts)) if exts else 'tất cả'), out_folder)})
    provider = make_provider(cfg)               # 1 provider dùng chung cho mọi file
    agg = {'files': len(files), 'files_done': 0, 'bad': 0, 'errors': 0}
    try:
        for idx, rel in enumerate(files):
            if stop.is_set(): break
            src_path = os.path.join(folder, rel); out_path = os.path.join(out_folder, rel)
            try:
                os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
            except Exception as e:
                emit({'type': 'log', 'msg': '!! Bỏ qua %s (không tạo được thư mục đích: %s)' % (rel, e)})
                agg['errors'] += 1; continue
            emit({'type': 'folder_file', 'index': idx, 'total': len(files), 'name': rel,
                  'state': 'start', 'files_done': agg['files_done']})
            file_cfg = dict(cfg); file_cfg['src'] = src_path; file_cfg['out'] = out_path
            captured = {}
            def file_emit(evt):
                t = evt.get('type')
                if t == 'finished':                          # nuốt finished từng file (gom vào agg)
                    captured.clear(); captured.update(evt); return
                if t == 'log':                               # gắn tên file vào log để dễ theo dõi
                    evt = {**evt, 'msg': '[%s] %s' % (rel, evt.get('msg', ''))}
                emit(evt)
            try:
                TranslationRun(file_cfg, file_emit, stop, provider=provider).run()
            except Exception as e:
                emit({'type': 'log', 'msg': '!! LỖI ở %s: %s' % (rel, str(e)[:120])})
                captured = {'status': 'error'}
            agg['bad'] += captured.get('bad', 0)
            st = captured.get('status')
            if st == 'ok': agg['files_done'] += 1
            elif st == 'error': agg['errors'] += 1
            emit({'type': 'folder_file', 'index': idx, 'total': len(files), 'name': rel,
                  'state': 'done', 'file_status': st or 'stopped', 'files_done': agg['files_done']})
    finally:
        try: provider.close()
        except Exception: pass
    if stop.is_set():
        emit({'type': 'finished', 'status': 'stopped', 'total': agg['files'], 'done': agg['files_done'],
              'bad': agg['bad'], 'msg': 'Đã dừng — %d/%d file xong (mở lại bấm Bắt đầu để dịch tiếp).'
              % (agg['files_done'], agg['files'])})
    else:
        status = 'ok' if agg['errors'] == 0 else 'error'
        extra = (', %d file lỗi' % agg['errors']) if agg['errors'] else ''
        emit({'type': 'finished', 'status': status, 'total': agg['files'], 'done': agg['files_done'],
              'bad': agg['bad'], 'msg': 'HOÀN TẤT THƯ MỤC — %d/%d file xong, %d dòng nghi lỗi%s.'
              % (agg['files_done'], agg['files'], agg['bad'], extra)})
